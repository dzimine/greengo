import os
import errno
import fire
import json
import yaml
import shutil
import urllib
from time import sleep
import logging
from boto3 import session
from botocore.exceptions import ClientError

# Set up Logging
logging.basicConfig(
    format='[gg] %(levelname).4s-%(lineno)d: %(message)s',
    level=logging.WARNING)
log = logging.getLogger('greengo')
log.setLevel(logging.DEBUG)

# Where do we want to save group state data? Where should we get the Root Certificate from?
DEFINITION_FILE = 'greengo.yaml'
MAGIC_DIR = '.gg'
STATE_FILE = os.path.join(MAGIC_DIR, 'gg_state.json')
ROOT_CA_URL = "https://www.amazontrust.com/repository/AmazonRootCA1.pem"

DEPLOY_TIMEOUT = 90  # Timeout, seconds

class GroupCommands(object):
    def __init__(self, config_file=DEFINITION_FILE, bulk=False):
        global STATE_FILE, DEFINITION_FILE, MAGIC_DIR

        # Get the current session data from AWS' Boto3
        s = session.Session()
        self._region = s.region_name
        if not self._region:
            log.error("AWS credentials and region must be setup. "
                      "Refer AWS docs at https://goo.gl/JDi5ie")
            exit(-1)

        log.info("AWS credentials found for region '{}'".format(self._region))

        # Set up a way to talk to each of the used AWS services
        self._gg = s.client("greengrass")
        self._iot = s.client("iot")
        self._lambda = s.client("lambda")
        self._iam = s.client("iam")
        self._iot_endpoint = self._iot.describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']

        DEFINITION_FILE = config_file

        # Get the configuration file
        try:
            with open(DEFINITION_FILE, 'r') as f:
                self.group = yaml.safe_load(f)
        except IOError:
            log.error("Group definition file "+DEFINITION_FILE+" not found. "
                      "Create file, and define the group definition first. "
                      "See https://github.com/greengo for details.")
            exit(-1)

        self.name = self.group['Group']['name']
        self._LAMBDA_ROLE_NAME = "{0}_Lambda_Role".format(self.name)

        # If we are doing bulk deployment, create a new folder to save all of the relevant information about that group
        if bulk:
            log.info("Bulk Creation Enabled")
            MAGIC_DIR = self.name + "-GG-Config"
            STATE_FILE = os.path.join(MAGIC_DIR, 'gg_state.json')

        _mkdir(MAGIC_DIR)
        self.state = _load_state()

    # Create a new GreenGrass Group
    def create(self):
        if self.state:
            log.error("Previously created group exists. Remove before creating!")
            return False

        log.info("[BEGIN] creating group {0}".format(self.group['Group']['name']))

        # TODO: create_lambda handles self.state directly.
        #       _create_cores leaves it to a caller. Refactor?

        # 1. Create group
        # TODO: create group at the end, with "initial version"?
        group = rinse(self._gg.create_group(Name=self.group['Group']['name']))
        self.state['Group'] = group
        _update_state(self.state)
        # Must update state on every step, else how can I clean?
        # Or on exception?

        # 2. Create core a) thing b) attach to group
        self._create_cores()

        # 5. Create devices
        self._create_devices(update_group_version=False)

        # 3. Create Resources - policies for local and ML resource access.
        self.create_resources()

        # 4. Create Lambda functions and function definitions
        #    Lambda may have dependencies on resources.
        #    TODO: refactor to take dependencies into account
        self.create_lambdas(update_group_version=False)

        self.create_connectors(update_group_version=False)

        # 6. Create subscriptions
        self.create_subscriptions(update_group_version=False)

        # 7. Create logger definitions
        self.create_loggers()  # TODO: I'll also need group-version update to change it later...

        # LAST. Add all the constituent parts to the Greengrass Group
        self.create_group_version()

        log.info("[END] creating group {0}".format(self.group['Group']['name']))

    # Create the file containing the root certificate
    def create_root_key(self):
        # If the file is not found in the certificates directory, go to the URL defined above and save the contents in the file named "root.ca.pem"
        if not os.path.isfile(self.group['certs']['keypath'] + "/root.ca.pem"):
            urllib.urlretrieve(
                ROOT_CA_URL,
                self.group['certs']['keypath'] + "/root.ca.pem")

    # Deploy lambda function and any other data to each of the GreenGrass Cores
    def deploy(self):
        if not self.state:
            log.info("There is nothing to deploy. Do create first.")
            return

        log.info("Deploying group '{0}'".format(self.state['Group']['Name']))

        # Start out by creating a deployment by getting the group id and the version id
        # DeploymentType is set to NewDeployment as default since we are not modified an existing dpeloyment
        deployment = self._gg.create_deployment(
            GroupId=self.state['Group']['Id'],
            GroupVersionId=self.state['Group']['Version']['Version'],
            DeploymentType="NewDeployment")
        self.state['Deployment'] = rinse(deployment)
        _update_state(self.state)

        # This loop will display the status of the current deployment to the terminal
        for i in range(DEPLOY_TIMEOUT // 2):
            sleep(2)
            # every two seconds check what the deployment status is

            deployment_status = self._gg.get_deployment_status(
                GroupId=self.state['Group']['Id'],
                DeploymentId=deployment['DeploymentId'])

            status = deployment_status.get('DeploymentStatus')

            log.debug("--- deploying... status: {0}".format(status))
            # Known status values: ['Building | InProgress | Success | Failure']
            if status == 'Success':
                log.info("--- SUCCESS!")
                self.state['Deployment']['Status'] = rinse(deployment_status)
                _update_state(self.state)
                return
            elif status == 'Failure':
                log.error("--- ERROR! {0}".format(deployment_status['ErrorMessage']))
                self.state['Deployment']['Status'] = rinse(deployment_status)
                _update_state(self.state)
                return
        # If the deployment is not complete by the deploy timeout, then quit. Something probably went wrong.
        log.warning(
            "--- Gave up waiting for deployment. Please check the status later. "
            "Make sure GreenGrass Core is running, connected to network, "
            "and the certificates match.")

    # Create a version of a group that has already been created
    def create_group_version(self):

        # Create a copy so that referencing non-existent fileds not create them in self.state
        state = State(self.state)

        kwargs = dict(
            GroupId=self.state['Group']['Id'],
            CoreDefinitionVersionArn=state['CoreDefinition']['LatestVersionArn'],
            DeviceDefinitionVersionArn=state['DeviceDefinition']['LatestVersionArn'],
            FunctionDefinitionVersionArn=state['FunctionDefinition']['LatestVersionArn'],
            SubscriptionDefinitionVersionArn=state['Subscriptions']['LatestVersionArn'],
            LoggerDefinitionVersionArn=state['Loggers']['LatestVersionArn'],
            ResourceDefinitionVersionArn=state['Resources']['LatestVersionArn'],
            ConnectorDefinitionVersionArn=state['Connectors']['LatestVersionArn']
        )

        args = dict((k, v) for k, v in kwargs.items() if v)

        log.debug("Creating group version with settings:\n{0}".format(pretty(args)))

        group_ver = self._gg.create_group_version(**args)

        self.state['Group']['Version'] = rinse(group_ver)
        _update_state(self.state)

    # Remove all of the components that we created through Greengo
    def remove(self):
        if not self.state:
            log.info("There seem to be nothing to remove.")
            return

        log.info("[BEGIN] removing group {0}".format(self.group['Group']['name']))

        # 1. Remove all of the subscriptions
        self.remove_subscriptions()

        # 2. Remove all of the cores and the associated devices and certs
        self._remove_cores()

        # 3. Remove all devices definitions and associated certificates
        self._remove_devices()

        # 4. Remove all of the lambdas
        self.remove_lambdas()

        # 5. Remove all of the other resources that were being used (AI/ML related specifically)
        self.remove_resources()

        # 6. Reset all of the deployments - otherwise GreenGrass won't let us delete the group
        log.info("Reseting deployments forcefully, if they exist")
        self._gg.reset_deployments(GroupId=self.state['Group']['Id'], Force=True)

        # 7. Delete the group
        log.info("Deleting group '{0}'".format(self.state['Group']['Id']))
        self._gg.delete_group(GroupId=self.state['Group']['Id'])

        # 8. Now that've removed the GreenGrass group, it is safe to delete the state file describing the current state of the group
        os.remove(STATE_FILE)

        log.info("[END] removing group {0}".format(self.group['Group']['name']))

    # Create a default role for the Lambda Function
    def _default_lambda_role_arn(self):
        if 'LambdaRole' not in self.state:
            log.info("Creating default lambda role '{0}'".format(self._LAMBDA_ROLE_NAME))
            try:
                role = self._create_default_lambda_role()
            except ClientError as e:
                if e.response['Error']['Code'] == 'EntityAlreadyExists':
                    role = self._iam.get_role(RoleName=self._LAMBDA_ROLE_NAME)
                    log.warning("Role {0} already exists, reusing.".format(self._LAMBDA_ROLE_NAME))
                else:
                    raise e

            self.state['LambdaRole'] = rinse(role)
            _update_state(self.state)
        # once a default lambda role has been created with access to the Lambda, return the ARN
        return self.state['LambdaRole']['Role']['Arn']

    # Update the current code for the Lambda only if a Lambda already exists
    def update_lambda(self, lambda_name):
        if not (self.state and self.state.get('Lambdas')):
            log.info("No lambdas created. Create first...")
            return

        # TODO: need to pop the dict from array (to replace later.. or replace in place?)
        lr = next((lr for lr in self.state['Lambdas'] if lr['FunctionName'] == lambda_name), None)
        if not lr:
            log.error("No lambda function '{0}' found.".format(lambda_name))
            return

        l = next((l for l in self.group['Lambdas'] if l['name'] == lambda_name), None)
        if not l:
            log.error("No definition for lambda function '{0}'.".format(lambda_name))
            return

        log.info("Updating lambda function code for '{0}'".format(lr['FunctionName']))

        # Zip the directory - Maybe we should consider using S3
        zf = shutil.make_archive(
            os.path.join(MAGIC_DIR, l['name']), 'zip', l['package'])
        log.debug("Lambda deployment Zipped to '{0}'".format(zf))

        # Update the Lambda Function Code, get the new version number
        with open(zf, 'rb') as f:
            lr_updated = self._lambda.update_function_code(
                FunctionName=l['name'],
                ZipFile=f.read(),
                Publish=True
            )

        lr.update(rinse(lr_updated))
        _update_state(self.state)
        log.info("Lambda function '{0}' updated".format(lr['FunctionName']))

        log.info("Updating alias '{0}'...".format(l.get('alias', 'default')))

        # Update the Alias to point to the most recent version of the Lambda
        alias = self._lambda.update_alias(
            FunctionName=lr['FunctionName'],
            Name=l.get('alias', 'default'),
            FunctionVersion=lr['Version']
        )

        log.info("Lambda alias updated. FunctionVersion:'{0}', Arn:'{1}'".format(
            alias['FunctionVersion'], alias['AliasArn']))
        # TODO: save alias? If so, where? If the alias name changed in group,
        # then LambdaDefinitions should also be updated.

        log.info("Lambdas function {0} updated OK!".format(lambda_name))

    # Create a lambda or link lambda to the new GreenGrass Group is already exists
    def create_lambdas(self, update_group_version=True):
        # if yaml file does not contain lambdas
        if not self.group.get('Lambdas'):
            log.info("Lambdas not defined. Moving on...")
            return
        # we want to create existing lambdas!
        # if self.state and self.state.get('Lambdas'):
        #     log.warning("Previously created Lambdas exists. Remove before creating!")
        #     return

        functions = []
        self.state['Lambdas'] = []
        _update_state(self.state)

        # For every lambda function that needs to be added
        for l in self.group['Lambdas']:

            log.info("Creating Lambda function '{0}'".format(l['name']))

            role_arn = l['role'] if 'role' in l else self._default_lambda_role_arn()
            log.info("Assuming role '{0}'".format(role_arn))
            # Check if the lambda is already created (by looking at the config file)
            already_defined = not ('handler' in l)

            # if it is not defined then make a zip and create a lambda function with that code
            # TODO: should we be using S3 instead of a zip upload?
            if not already_defined:
                zf = shutil.make_archive(
                    os.path.join(MAGIC_DIR, l['name']), 'zip', l['package'])
                log.debug("Lambda deployment Zipped to '{0}'".format(zf))

                for retry in range(3):
                    try:
                        with open(zf, 'rb') as f:
                            lr = self._lambda.create_function(
                                FunctionName=l['name'],
                                Runtime='python2.7', # need to eventually change the default to python3 eventually since python 2.7 support ends soon
                                Role=role_arn,
                                Handler=l['handler'],
                                Code=dict(ZipFile=f.read()),
                                Environment=dict(Variables=l.get('environment', {})),
                                Publish=True
                            )
                            # Break from retry cycle if lambda is created
                            break
                    except ClientError as e:  # Catch the right exception
                        if "The role defined for the function cannot be assumed by Lambda" in str(e):
                            # Function creation immediately after role creation fails with
                            # "The role defined for the function cannot be assumed by Lambda."
                            # See StackOverflow https://goo.gl/eTfqsS
                            log.warning("We hit AWS bug: the role is not yet propagated."
                                        "Taking 10 sec nap")
                            sleep(10)
                            continue
                        else:
                            raise(e)

                lr['ZipPath'] = zf
            # if the lambda function is already defined get the current state and set already_defined to True
            else:
                lr = self._lambda.get_function_configuration(
                    FunctionName=l['name'],
                    Qualifier=l['alias']
                )
                lr['already_defined'] = True
            self.state['Lambdas'].append(rinse(lr))
            _update_state(self.state)
            log.info("Lambda function '{0}' created".format(lr['FunctionName']))

            # Auto-created alias uses the version of just published function
            if not already_defined:
                alias = self._lambda.create_alias(
                    FunctionName=lr['FunctionName'],
                    Name=l.get('alias', 'default'),
                    FunctionVersion=lr['Version'],
                    Description='Created by greengo'
                )
            else:
                alias = self._lambda.get_alias(
                FunctionName=lr['FunctionName'],
                Name=l.get('alias', 'default')
                )
            log.info("Lambda alias created. FunctionVersion:'{0}', Arn:'{1}'".format(
                alias['FunctionVersion'], alias['AliasArn']))

            # append the new lambda function to the list of functions that will be saved later
            functions.append({
                'Id': l['name'],
                'FunctionArn': alias['AliasArn'],
                'FunctionConfiguration': l['greengrassConfig']
            })

        log.debug("Function definition list ready:\n{0}".format(pretty(functions)))

        log.info("Creating function definition: '{0}'".format(self.name + '_func_def_1'))

        # Now that we have the lambda created, add the function to the GreenGrassGroup
        fd = self._gg.create_function_definition(
            Name=self.name + '_func_def_1',
            InitialVersion={'Functions': functions}
        )
        self.state['FunctionDefinition'] = rinse(fd)
        _update_state(self.state)

        fd_ver = self._gg.get_function_definition_version(
            FunctionDefinitionId=self.state['FunctionDefinition']['Id'],
            FunctionDefinitionVersionId=self.state['FunctionDefinition']['LatestVersion'])

        self.state['FunctionDefinition']['LatestVersionDetails'] = rinse(fd_ver)
        _update_state(self.state)

        # if we need to update the group version, then do it by creating a new group version
        if update_group_version:
            log.info("Updating group version with new Lambdas...")
            self.create_group_version()

        log.info("Lambdas and function definition created OK!")

    # Remove Lambda Functions
    def remove_lambdas(self):
        if not (self.state and self.state.get('Lambdas')):
            log.info("There seem to be no Lambdas to remove.")
            return

        if not self.state.get('FunctionDefinition'):
            log.warning("Function definition was not created. Moving on...")
        else:
            log.info("Deleting function definition '{0}' Id='{1}".format(
                self.state['FunctionDefinition']['Name'], self.state['FunctionDefinition']['Id']))
            # First, delete the function definition so that it is no longer associated with the greengrass group
            self._gg.delete_function_definition(
                FunctionDefinitionId=self.state['FunctionDefinition']['Id'])
            self.state.pop('FunctionDefinition')
            _update_state(self.state)

        # Delete the IAM role that is associated with the Lambda Function
        log.info("Deleting default lambda role '{0}'".format(self._LAMBDA_ROLE_NAME))
        self._remove_default_lambda_role()
        self.state.pop('LambdaRole')
        _update_state(self.state)

        # If the lambda function was not previously defined when the group was created, then delete the lambda function
        # otherwise leave it alone
        for l in self.state['Lambdas']:
            already_defined = ('already_defined' in l)

            if not already_defined:
                log.info("Deleting Lambda function '{0}'".format(l['FunctionName']))
                self._lambda.delete_function(FunctionName=l['FunctionName'])
                os.remove(l['ZipPath'])

        self.state.pop('Lambdas')
        _update_state(self.state)

        log.info("Lambdas and function definition deleted OK!")

    # Create a subscription so that the cores/cloud/resources/other knows which messages it should be listening for
    def create_subscriptions(self, update_group_version=True):
        if not self.group.get('Subscriptions'):
            log.info("Subscriptions not defined. Moving on...")
            return

        if self.state and self.state.get('Subscriptions'):
            log.warning("Previously created Subscriptions exists. Remove before creating!")
            return
        # MAYBE: don't create subscription before devices and lambdas?

        # Create a list of all of the subscriptions that need to be created
        log.debug("Preparing subscription list...")
        subs = []
        for i, s in enumerate(self.group['Subscriptions']):
            log.debug("Subscription '{0}' - '{1}': {2}->{3}'".format(
                i, s['Subject'], s['Source'], s['Target']))
            subs.append({
                'Id': str(i),
                'Source': self._resolve_subscription_destination(s['Source']),
                'Target': self._resolve_subscription_destination(s['Target']),
                'Subject': s['Subject']
            })
        log.debug("Subscription list is ready:\n{0}".format(pretty(subs)))

        # Create a subscription definition with the lsit of the subscriptions generated above
        log.info("Creating subscription definition: '{0}'".format(self.name + '_subscription'))
        sub_def = self._gg.create_subscription_definition(
            Name=self.name + '_subscription',
            InitialVersion={'Subscriptions': subs}
        )

        self.state['Subscriptions'] = rinse(sub_def)
        _update_state(self.state)

        # Get the subscription definition version so that we can save it in the state file
        sub_def_ver = self._gg.get_subscription_definition_version(
            SubscriptionDefinitionId=self.state['Subscriptions']['Id'],
            SubscriptionDefinitionVersionId=self.state['Subscriptions']['LatestVersion'])

        self.state['Subscriptions']['LatestVersionDetails'] = rinse(sub_def_ver)
        _update_state(self.state)

        # if we need to update the group version, do that
        if update_group_version:
            log.info("Updating group version with new Lambdas...")
            self.create_group_version()

        log.info("Subscription definition created OK!")

    # Remove all of the subscriptions
    def remove_subscriptions(self):
        if not (self.state and self.state.get('Subscriptions')):
            log.info("There seem to be no Subscriptions to remove.")
            return

        # Delete the subscription definition - this will automatically delete all of the subscriptions
        log.info("Deleting subscription definition '{0}' Id='{1}".format(
            self.state['Subscriptions']['Name'], self.state['Subscriptions']['Id']))
        self._gg.delete_subscription_definition(
            SubscriptionDefinitionId=self.state['Subscriptions']['Id'])

        # Remove subscriptions from the state file
        self.state.pop('Subscriptions')
        _update_state(self.state)
        log.info("Subscription definition deleted OK!")

    # Modify the subscription services from the config file to official AWS names
    def _resolve_subscription_destination(self, d):
        p = [x.strip() for x in d.split('::')]
        if p[0] == 'cloud':
            return p[0]
        elif p[0] == 'Lambda':
            return self._lookup_lambda_qualified_arn(p[1])
        elif p[0] == 'Device':
            return self._lookup_device_arn(p[1])
        elif p[0] == 'GGShadowService':
            return p[0]
        elif p[0] == 'Connector':
            return self._lookup_connector_arn(p[1])
        else:
            raise ValueError(
                "Error parsing subscription destination '{0}'. Allowed values: "
                "'Lambda::', 'Device::', 'Connector::', 'GGShadowService', or 'cloud'.".format(d))

    # Get the Lambda ARN
    def _lookup_lambda_qualified_arn(self, name):
        details = self.state['FunctionDefinition']['LatestVersionDetails']
        for l in details['Definition']['Functions']:
            if l['Id'] == name:
                return l['FunctionArn']
        log.error("Lambda '{0}' not found".format(name))
        return None

    # Get the Device ARN
    def _lookup_device_arn(self, name):
        details = self.state['DeviceDefinition']['LatestVersionDetails']
        for l in details['Definition']['Devices']:
            if l['Id'] == name:
                return l['ThingArn']
        log.error("Device '{0}' not found".format(name))
        return None

    # Get the Connector ARN
    def _lookup_connector_arn(self, name):
        details = self.state['Connectors']['LatestVersionDetails']
        for l in details['Definition']['Connectors']:
            if l['Id'] == name:
                return l['ConnectorArn']
        log.error("Connector '{0}' not found".format(name))
        return None

    # Create Resources (specifically those like AI/ML things)
    def create_resources(self):
        if not self.group.get('Resources'):
            log.info("Resources not defined. Moving on...")
            return

        # Remove old resources before creating new resources
        if self.state and self.state.get('Resources'):
            log.warning("Previously created Resources exist. Remove before creating!")
            return


        log.debug("Preparing Resources ...")
        res = []
        # Create the list of resources similar to the subscriptions list
        for r in self.group['Resources']:
            # Convert from a simplified form
            resource = dict(Name=r.pop('Name'), Id=r.pop('Id'))
            resource['ResourceDataContainer'] = r
            res.append(resource)

        log.debug("Resources list is ready:\n{0}".format(pretty(res)))

        # Create the resource definition
        name = self.name + '_resources'
        log.info("Creating resource definition: '{0}'".format(name))
        res_def = self._gg.create_resource_definition(
            Name=name,
            InitialVersion={'Resources': res}
        )

        self.state['Resources'] = rinse(res_def)
        _update_state(self.state)

        # Get the Resource Definition Version
        res_def_ver = self._gg.get_resource_definition_version(
            ResourceDefinitionId=self.state['Resources']['Id'],
            ResourceDefinitionVersionId=self.state['Resources']['LatestVersion'])

        self.state['Resources']['LatestVersionDetails'] = rinse(res_def_ver)
        _update_state(self.state)

        log.info("Resources definition created OK!")

    # Remove all of the current resources
    def remove_resources(self):
        if not (self.state and self.state.get('Resources')):
            log.info("There seem to be no Resources to remove.")
            return

        log.info("Deleting resources definition '{0}' Id='{1}".format(
            self.state['Resources']['Name'], self.state['Resources']['Id']))

        # Delete the Resource Definition from the GreenGrass Group
        self._gg.delete_resource_definition(
            ResourceDefinitionId=self.state['Resources']['Id'])

        self.state.pop('Resources')
        _update_state(self.state)
        log.info("Resources definition deleted OK!")

    # Create loggers to gather data
    def create_loggers(self):
        if not self.group.get('Loggers'):
            log.info("Loggers not defined. Moving on...")
            return

        if self.state and self.state.get('Loggers'):
            log.warning("Previously created Loggers exist. Remove before creating!")
            return

        loggers = self.group['Loggers']
        name = self.name + '_loggers'
        log.info("Creating loggers definition: '{0}'".format(name))

        # Create the Logger Definition
        res_def = self._gg.create_logger_definition(
            Name=name,
            InitialVersion={'Loggers': loggers}
        )

        self.state['Loggers'] = rinse(res_def)
        _update_state(self.state)

        # Get the logger definition so that we can save needed data in the state file
        log_def_ver = self._gg.get_logger_definition_version(
            LoggerDefinitionId=self.state['Loggers']['Id'],
            LoggerDefinitionVersionId=self.state['Loggers']['LatestVersion'])

        self.state['Loggers']['LatestVersionDetails'] = rinse(log_def_ver)
        _update_state(self.state)

        log.info("Loggers definition created OK!")

    # Remove the loggers
    def remove_loggers(self):
        if not (self.state and self.state.get('Loggers')):
            log.info("There seem to be no Loggers to remove.")
            return
        log.info("Deleting loggers definition Id='{0}'".format(
            self.state['Loggers']['Id']))

        # Remove the logger definition
        self._gg.delete_logger_definition(
            LoggerDefinitionId=self.state['Loggers']['Id'])

        self.state.pop('Loggers')
        _update_state(self.state)
        log.info("Loggers definition deleted OK!")

    # TODO: REFACTOR.
    # Connectors, Loggers, and Subscription code are all the same, exactly.
    def create_connectors(self, update_group_version=True):
        if not self.group.get('Connectors'):
            log.info("Connectors not defined. Moving on...")
            return

        if self.state and self.state.get('Connectors'):
            log.warning("Previously created Connectors exist. Remove before creating!")
            return

        connectors = self.group['Connectors']
        name = self.name + '_connectors'
        log.info("Creating connectors definition: '{0}'".format(name))

        d = self._gg.create_connector_definition(
            Name=name,
            InitialVersion={'Connectors': connectors}
        )

        self.state['Connectors'] = rinse(d)
        _update_state(self.state)

        d_ver = self._gg.get_connector_definition_version(
            ConnectorDefinitionId=self.state['Connectors']['Id'],
            ConnectorDefinitionVersionId=self.state['Connectors']['LatestVersion'])

        self.state['Connectors']['LatestVersionDetails'] = rinse(d_ver)
        _update_state(self.state)

        if update_group_version:
            log.info("Updating group version with new Connectors...")
            self.create_group_version()

        log.info("Connectors definition created OK!")

    # TODO: REFACTOR
    # Remove all of the connectors
    def remove_connectors(self):
        if not (self.state and self.state.get('Connectors')):
            log.info("There seem to be no connectors to remove.")
            return
        log.info("Deleting connector definition Id='{0}'".format(
            self.state['Connectors']['Id']))

        self._gg.delete_connector_definition(
            ConnectorDefinitionId=self.state['Connectors']['Id'])

        self.state.pop('Connectors')
        _update_state(self.state)
        log.info("Connectors definition deleted OK!")

    # Update everything by removing all of the subscriptions, lambdas and resources and then re-adding them to the GreenGrass Group
    def update(self):
        self.remove_subscriptions()
        self.remove_lambdas()
        self.remove_resources()
        # self.remove_devices()
        self.create_resources()
        self.create_lambdas()
        self.create_subscriptions()

        self.create_group_version()

        log.info('Updated on Greengrass! Execute "greengo deploy" to apply')

    # Create and generate associated structures for non-core Devices
    # that will connect to the core.
    def _create_devices(self, update_group_version=True):
        # TODO: Refactor-handle state internally, make callable individually
        #       Maybe reflet dependency tree in self.group/greensgo.yaml and travel it
        self.state['Devices'] = []
        devices = []
        initial_version = {'Devices': []}

        for device_description in self.group['Devices']:
            try:
                # Create the IOT thing and get the certificates
                name = device_description['name']
                log.info("Creating a thing for core {0}".format(name))
                keys_cert = rinse(self._iot.create_keys_and_certificate(setAsActive=True))
                device_thing = rinse(self._iot.create_thing(thingName=name))

                # Attach the previously created Certificate to the created Thing
                self._iot.attach_thing_principal(
                    thingName=name, principal=keys_cert['certificateArn'])
                policy = self._create_and_attach_thing_policy(
                    thing_name=name,
                    policy_doc=self._create_device_policy(),
                    thing_cert_arn=keys_cert['certificateArn']
                )

                # Add all of the relevant data to the devices list for the state update
                devices.append({
                    'name': name,
                    'thing': device_thing,
                    'keys': keys_cert,
                    'policy': policy
                })

                # Save the details pertaining to the certificate linked with the thing ARN
                initial_version['Devices'].append({
                    'Id': name,
                    'CertificateArn': keys_cert['certificateArn'],
                    'SyncShadow': device_description['SyncShadow'],
                    'ThingArn': device_thing['thingArn']
                })

                # Save the certificates in the appropriate location
                _save_keys(device_description['key_path'], name, keys_cert)

            except Exception as e:
                log.error("Error creating device {0}: {1}".format(name, str(e)))
                # Continue with other devices if any
        self.state['Devices'] = devices
        _update_state(self.state)
        log.debug("Creating Device definition with InitialVersion={0}".format(
            initial_version))

        # Create the device definition
        device_def = rinse(self._gg.create_device_definition(
            Name=self.name + '_func_def_1',
            InitialVersion=initial_version
        ))

        self.state['DeviceDefinition'] = device_def
        _update_state(self.state)
        log.info("Created Device definition Arn:{0} Id:{1}".format(
            device_def['Arn'], device_def['Id']))

        # Get the device definition version
        device_ver = self._gg.get_device_definition_version(
            DeviceDefinitionId=self.state['DeviceDefinition']['Id'],
            DeviceDefinitionVersionId=self.state['DeviceDefinition']['LatestVersion'])

        self.state['DeviceDefinition']['LatestVersionDetails'] = rinse(device_ver)
        _update_state(self.state)

        self.state['Devices'] = devices

        _update_state(self.state)

        # Create a new group version if needed
        if update_group_version:
            log.info("Updating group version with new Lambdas...")
            self.create_group_version()
        log.info("Devices and definition created OK!")

    def _create_cores(self):
        # TODO: Refactor-handle state internally, make callable individually
        #       Maybe reflet dependency tree in self.group/greensgo.yaml and travel it
        self.state['Cores'] = []
        _update_state(self.state)
        cores = []
        initial_version = {'Cores': []}

        for core in self.group['Cores']:
            try:
                # Create the core and get the certificates
                name = core['name']
                log.info("Creating a thing for core {0}".format(name))
                keys_cert = rinse(self._iot.create_keys_and_certificate(setAsActive=True))
                core_thing = rinse(self._iot.create_thing(thingName=name))

                # Attach the previously created Certificate to the created Thing
                self._iot.attach_thing_principal(
                    thingName=name, principal=keys_cert['certificateArn'])
                policy = self._create_and_attach_thing_policy(
                    thing_name=name,
                    policy_doc=self._create_core_policy(),
                    thing_cert_arn=keys_cert['certificateArn']
                )

                # Append to list of the cores
                # There should only be 1...
                cores.append({
                    'name': name,
                    'thing': core_thing,
                    'keys': keys_cert,
                    'policy': policy
                })

                # Add the code to the initial_version list
                # Again, there should only be 1...
                initial_version['Cores'].append({
                    'Id': name,
                    'CertificateArn': keys_cert['certificateArn'],
                    'SyncShadow': core['SyncShadow'],
                    'ThingArn': core_thing['thingArn']
                })

                # Save the certificates and the config file used to run the core
                _save_keys(core['key_path'], name, keys_cert)

                self._create_ggc_config_file(core['config_path'], "config.json", core_thing)

            except Exception as e:
                log.error("Error creating core {0}: {1}".format(name, str(e)))
                # Continue with other cores if any

            log.debug("Creating Core definition with InitialVersion={0}".format(
                initial_version))

            # Create the core definition
            core_def = rinse(self._gg.create_core_definition(
                Name="{0}_core_def".format(self.group['Group']['name']),
                InitialVersion=initial_version
            ))

            log.info("Created Core definition Arn:{0} Id:{1}".format(
                core_def['Arn'], core_def['Id']))

        self.state['Cores'] = cores

        self.state['CoreDefinition'] = core_def

        _update_state(self.state)

    # Remove all of the devices and detach associated structures
    def _remove_devices(self):
        # TODO: protect with try/catch ClientError
        # for every device
        for device in self.state['Devices']:
            thing_name = device['thing']['thingName']
            cert_id = device['keys']['certificateId']
            log.info("Removing device thing '{0}'' from device '{1}'".format(
                device['name'], thing_name))

            log.debug("--- detaching policy: '{0}'".format(device['policy']['policyName']))
            self._iot.detach_principal_policy(
                policyName=device['policy']['policyName'], principal=device['keys']['certificateArn'])

            log.debug("--- deleting policy: '{0}'".format(device['policy']['policyName']))
            self._iot.delete_policy(policyName=device['policy']['policyName'])

            log.debug("--- deactivating certificate: '{0}'".format(device['keys']['certificateId']))
            self._iot.update_certificate(
                certificateId=cert_id, newStatus='INACTIVE')

            log.debug(
                "--- detaching certificate '{0}' from thing '{1}'".format(cert_id, thing_name))
            self._iot.detach_thing_principal(
                thingName=thing_name, principal=device['keys']['certificateArn'])
            sleep(1)

            log.debug("--- deleting certificate: '{0}'".format(device['keys']['certificateId']))
            self._iot.delete_certificate(certificateId=device['keys']['certificateId'])

            log.debug("--- deleting thing: '{0}'".format(device['thing']['thingName']))
            self._iot.delete_thing(thingName=device['thing']['thingName'])

        device_def = self.state['DeviceDefinition']
        log.info("Removing device definition '{0}'".format(device_def['Name']))
        self._gg.delete_device_definition(DeviceDefinitionId=device_def['Id'])

    # Remove the core for the GreenGrass Group
    def _remove_cores(self):
        # TODO: protect with try/catch ClientError
        for core in self.state['Cores']:
            thing_name = core['thing']['thingName']
            cert_id = core['keys']['certificateId']
            log.info("Removing core thing '{0}'' from core '{1}'".format(
                core['name'], thing_name))

            log.debug("--- detaching policy: '{0}'".format(core['policy']['policyName']))
            self._iot.detach_principal_policy(
                policyName=core['policy']['policyName'], principal=core['keys']['certificateArn'])

            log.debug("--- deleting policy: '{0}'".format(core['policy']['policyName']))
            self._iot.delete_policy(policyName=core['policy']['policyName'])

            log.debug("--- deactivating certificate: '{0}'".format(core['keys']['certificateId']))
            self._iot.update_certificate(
                certificateId=cert_id, newStatus='INACTIVE')

            log.debug(
                "--- detaching certificate '{0}' from thing '{1}'".format(cert_id, thing_name))
            self._iot.detach_thing_principal(
                thingName=thing_name, principal=core['keys']['certificateArn'])
            sleep(1)

            log.debug("--- deleting certificate: '{0}'".format(core['keys']['certificateId']))
            self._iot.delete_certificate(certificateId=core['keys']['certificateId'])

            log.debug("--- deleting thing: '{0}'".format(core['thing']['thingName']))
            self._iot.delete_thing(thingName=core['thing']['thingName'])

        core_def = self.state['CoreDefinition']
        log.info("Removing core definition '{0}'".format(core_def['Name']))
        self._gg.delete_core_definition(CoreDefinitionId=core_def['Id'])

    # Create the IOT policy and attach it to the thing
    def _create_and_attach_thing_policy(self, thing_name, policy_doc, thing_cert_arn):
        try:
            policy_name = "{0}-policy".format(thing_name)
            policy = rinse(self._iot.create_policy(
                policyName=policy_name,
                policyDocument=policy_doc)
            )
        except ClientError as ce:
            if ce.response['Error']['Code'] == 'EntityAlreadyExists':
                log.warning(
                    "Policy '{0}' exists. Using existing Policy".format(policy_name))
            else:
                log.error("Unexpected Error: {0}".format(ce))
                raise

        self._iot.attach_principal_policy(
            policyName=policy_name,
            principal=thing_cert_arn
        )
        log.info("Created policy {0} for {1} and attached to certificate {2}".format(
            policy_name, thing_name, thing_cert_arn))

        return policy

    # Create the device policy json
    def _create_device_policy(self):
        # TODO: redo as template and read from definition file
        device_policy =  {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "iot:*"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "greengrass:*"
                    ],
                    "Resource": "*"
                }
            ]
        }
        return json.dumps(device_policy)

    # Create the core policy json
    def _create_core_policy(self):
        # TODO: redo as template and read from definition file
        core_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "iot:Publish",
                        "iot:Subscribe",
                        "iot:Connect",
                        "iot:Receive",
                        "iot:GetThingShadow",
                        "iot:DeleteThingShadow",
                        "iot:UpdateThingShadow"
                    ],
                    "Resource": ["arn:aws:iot:" + self._region + ":*:*"]
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "greengrass:AssumeRoleForGroup",
                        "greengrass:CreateCertificate",
                        "greengrass:GetConnectivityInfo",
                        "greengrass:GetDeployment",
                        "greengrass:GetDeploymentArtifacts",
                        "greengrass:UpdateConnectivityInfo",
                        "greengrass:UpdateCoreDeploymentStatus"
                    ],
                    "Resource": ["*"]
                }
            ]
        }
        return json.dumps(core_policy)

    # Create the config file to run the core appropriately
    def _create_ggc_config_file(self, path, name, core_thing):

        log.info("Creating GGC config file with core {0} at {1}/{2}".format(
            core_thing['thingName'], path, name))

        config = {
            "coreThing": {
                "caPath": "root.ca.pem",
                "certPath": core_thing['thingName'] + ".cert.pem",
                "keyPath": core_thing['thingName'] + ".private.key",
                "thingArn": core_thing['thingArn'],
                "iotHost": self._iot_endpoint,
                "ggHost": "greengrass-ats.iot." + self._region + ".amazonaws.com",
                "keepAlive": 600
            },
            "runtime": {
                "cgroup": {
                    "useSystemd": "yes"
                }
            },
            "managedRespawn": False,
            "crypto" : {
            "principals" : {
              "SecretsManager" : {
                "privateKeyPath" : "file:///greengrass/certs/" + core_thing['thingName'] + ".private.key"
              },
              "IoTCertificate" : {
                "privateKeyPath" : "file:///greengrass/certs/" + core_thing['thingName'] + ".private.key",
                "certificatePath" : "file:///greengrass/certs/" + core_thing['thingName'] + ".cert.pem"
              }
            },
            "caPath" : "file:///greengrass/certs/root.ca.pem"
          }
        }

        _mkdir(path)
        with open(path + '/' + name, 'w') as f:
            json.dump(config, f, indent=4, separators=(',', ' : '))

    # Creat the lambda role with the appropriate json and associate with it with the appropriate lambda function
    def _create_default_lambda_role(self):
        # TODO: redo as template and read from definition .yaml
        role_policy_document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "lambda.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"

                }
            ]
        }

        role = self._iam.create_role(
            RoleName=self._LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(role_policy_document)
        )

        inline_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Resource": "arn:aws:logs:*:*:*"
                }
            ]
        }

        self._iam.put_role_policy(
            RoleName=self._LAMBDA_ROLE_NAME,
            PolicyName=self._LAMBDA_ROLE_NAME + "-Policy",
            PolicyDocument=json.dumps(inline_policy))

        return role

    # Remove the default lambda role
    def _remove_default_lambda_role(self):
        for p in self._iam.list_role_policies(RoleName=self._LAMBDA_ROLE_NAME)['PolicyNames']:
            self._iam.delete_role_policy(RoleName=self._LAMBDA_ROLE_NAME, PolicyName=p)

        self._iam.delete_role(RoleName=self._LAMBDA_ROLE_NAME)

###############################################################################
# UTILITY FUNCTIONS

# Remove all of the HTTP stuff from the response
def rinse(boto_response):
    if 'ResponseMetadata' in boto_response:
        boto_response.pop('ResponseMetadata')
    return boto_response

# Make the yaml pretty
def pretty(d):
    """Pretty object as YAML."""
    return yaml.safe_dump(d, default_flow_style=False)

# Update the state by removing the old state file and re-writing it
def _update_state(group_state):
    if not group_state:
        os.remove(STATE_FILE)
        log.debug("State is empty, removed state file '{0}'".format(STATE_FILE))
        return

    with open(STATE_FILE, 'w') as f:
        json.dump(group_state, f, indent=2,
                  separators=(',', ': '), sort_keys=True, default=str)
        log.debug("Updated group state in state file '{0}'".format(STATE_FILE))

# Class that holds the state
class State(dict):

    def __missing__(self, k):  # noqa
        v = self[k] = type(self)()
        return v

# Check if the state exists by checking if the STATE_FILE exists in the directory
def _state_exists():
    return os.path.exists(STATE_FILE)

# Load the state from the STATE_FILE by reading it into a state object
def _load_state():
    if not _state_exists():
        log.debug("Group state file {0} not found, assume new group.".format(STATE_FILE))
        return {}
    log.debug("Loading group state from {0}".format(STATE_FILE))
    with open(STATE_FILE, 'r') as f:
        return State(json.load(f))

# Make a new directory given a directory path
def _mkdir(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if not (exc.errno == errno.EEXIST and os.path.isdir(path)):
            raise

# Save the keys in the appropriate place
def _save_keys(path, name, keys_cert):
    try:
        path = path + '/' if not path.endswith('/') else path
        _mkdir(path)
        certname = path + name + ".cert.pem" # IMPORTANT: make sure that .cert.pem is the extension
        public_key_file = path + name + ".pub" # IMPORTANT: make sure that .pub is the extension
        private_key_file = path + name + ".private.key" # IMPORTANT: make sure that .private.key is the extension

        # Write all of the certificate files to the correct location
        with open(certname, "w") as pem_file:
            pem = keys_cert['certificatePem']
            pem_file.write(pem)
            log.info("Thing Name: {0} and PEM file: {1}".format(name, certname))

        with open(public_key_file, "w") as pub_file:
            pub = keys_cert['keyPair']['PublicKey']
            pub_file.write(pub)
            log.info("Thing Name: {0} Public Key File: {1}".format(name, public_key_file))

        with open(private_key_file, "w") as prv_file:
            prv = keys_cert['keyPair']['PrivateKey']
            prv_file.write(prv)
            log.info("Thing Name: {0} Private Key File: {1}".format(name, private_key_file))

    except OSError as e:
        log.error('Error while writing an certificate files. {0}'.format(e))
    except KeyError as e:
        log.error('Error while writing an certificate files. {0}'
                  'Check the keys {1}'.format(e, keys_cert))

# Call fire to allow us to just call the method names from the command line
def main():
    fire.Fire(GroupCommands)

# Run main()
if __name__ == '__main__':
    main()
