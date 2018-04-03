import os
import errno
import fire
import json
import yaml
import shutil
from time import sleep
import logging
from boto3.session import Session
from botocore.exceptions import ClientError

logging.basicConfig(
    format='%(asctime)s|%(name).10s|%(levelname).5s: %(message)s',
    level=logging.WARNING)
log = logging.getLogger('greengo')
log.setLevel(logging.DEBUG)


DEFINITION_FILE = 'greengo.yaml'
MAGIC_DIR = '.gg'
STATE_FILE = os.path.join(MAGIC_DIR, 'gg_state.json')


class GroupCommands(object):
    def __init__(self):
        super(GroupCommands, self).__init__()

        session = Session()
        self._gg = session.client("greengrass")
        self._iot = session.client("iot")
        self._lambda = session.client("lambda")
        self._iam = session.client("iam")
        self._region = session.region_name
        self._iot_endpoint = self._iot.describe_endpoint()['endpointAddress']

        with open(DEFINITION_FILE, 'r') as f:
            self.group = self.group = yaml.safe_load(f)

        self.name = self.group['Group']['name']
        self.LAMBDA_ROLE_NAME = "{0}_Lambda_Role".format(self.name)

        _mkdir(MAGIC_DIR)
        self.state = _load_state()

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
        core_def, cores = self._create_cores()
        self.state['Cores'] = cores
        self.state['CoreDefinition'] = core_def
        _update_state(self.state)

        # 3. Create Lambda functions and function definitions
        self.create_lambdas()

        # 4. Create devices (coming soon)

        # 5. Create subscriptions
        self.create_subscriptions()

        # LAST. Add all the constituent parts to the Greengrass Group
        group_ver = self._gg.create_group_version(
            GroupId=self.state['Group']['Id'],
            CoreDefinitionVersionArn=self.state['CoreDefinition']['LatestVersionArn'],
            # DeviceDefinitionVersionArn="",
            FunctionDefinitionVersionArn=self.state['FunctionDefinition']['LatestVersionArn'],
            SubscriptionDefinitionVersionArn=self.state['Subscriptions']['LatestVersionArn'],
            # LoggerDefinitionVersionArn="",
        )

        self.state['Group']['Version'] = rinse(group_ver)
        _update_state(self.state)

        log.info("[END] creating group {0}".format(self.group['Group']['name']))

    def deploy(self):
        if not self.state:
            log.info("There is nothing to deploy. Do create first.")
            return

        log.info("Deploying group '{0}'".format(self.state['Group']['Name']))

        deployment = self._gg.create_deployment(
            GroupId=self.state['Group']['Id'],
            GroupVersionId=self.state['Group']['Version']['Version'],
            DeploymentType="NewDeployment")
        self.state['Deployment'] = rinse(deployment)
        _update_state(self.state)

        for i in range(15):
            sleep(2)
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

        log.warning(
            "--- Gave up waiting for deployment. Please check the status later. "
            "Make sure GreenGrass Core is running, connected to network, "
            "and the certificates match.")

    def remove(self):
        if not self.state:
            log.info("There seem to be nothing to remove.")
            return

        log.info("[BEGIN] removing group {0}".format(self.group['Group']['name']))

        self.remove_subscriptions()

        self._remove_cores()

        self.remove_lambdas()

        log.info("Reseting deployments forcefully, if they exist")
        self._gg.reset_deployments(GroupId=self.state['Group']['Id'], Force=True)

        log.info("Deleting group '{0}'".format(self.state['Group']['Id']))
        self._gg.delete_group(GroupId=self.state['Group']['Id'])

        os.remove(STATE_FILE)

        log.info("[END] removing group {0}".format(self.group['Group']['name']))

    def default_lambda_role_arn(self):
        if 'LambdaRole' not in self.state:
            log.info("Creating default lambda role '{0}'".format(self.LAMBDA_ROLE_NAME))
            role = self._create_default_lambda_role()
            self.state['LambdaRole'] = rinse(role)
            _update_state(self.state)
        return self.state['LambdaRole']['Role']['Arn']

    def create_lambdas(self):
        if self.state and self.state.get('Lambdas'):
            log.warning("Previously created Lambdas exists. Remove before creating!")
            return

        functions = []
        self.state['Lambdas'] = []
        _update_state(self.state)

        for l in self.group['Lambdas']:
            log.info("Creating Lambda function '{0}'".format(l['name']))

            role_arn = l['role'] if 'role' in l else self.default_lambda_role_arn()
            log.info("Assuming role '{0}'".format(role_arn))

            zf = shutil.make_archive(
                os.path.join(MAGIC_DIR, l['name']), 'zip', l['package'])
            log.debug("Lambda deployment Zipped to '{0}'".format(zf))

            for retry in range(3):
                try:
                    with open(zf, 'rb') as f:
                        lr = self._lambda.create_function(
                            FunctionName=l['name'],
                            Runtime='python2.7',
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
                        log.warning("We hit AWS bug: the role is not yet propogated."
                                    "Taking 10 sec nap")
                        sleep(10)
                        continue
                    else:
                        raise(e)

            lr['ZipPath'] = zf
            self.state['Lambdas'].append(rinse(lr))
            _update_state(self.state)
            log.info("Lambda function '{0}' created".format(lr['FunctionName']))

            # Auto-created alias uses the version of just published function
            alias = self._lambda.create_alias(
                FunctionName=lr['FunctionName'],
                Name=l.get('alias', 'default'),
                FunctionVersion=lr['Version'],
                Description='Created by greengo'
            )
            log.info("Lambda alias created. FunctionVersion:'{0}', Arn:'{1}'".format(
                alias['FunctionVersion'], alias['AliasArn']))

            functions.append({
                'Id': l['name'],
                'FunctionArn': alias['AliasArn'],
                'FunctionConfiguration': l['greengrassConfig']
            })

        log.debug("Function definition list ready:\n{0}".format(functions))

        log.info("Creating function definition: '{0}'".format(self.name + '_func_def_1'))
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

        log.info("Lambdas and function definition created OK!")

        # TODO: Update group version if group exists
        # group_ver = self._gg.create_group_version(
        #     GroupId=group['Id'],
        #     CoreDefinitionVersionArn=core_def['LatestVersionArn'],
        #     # DeviceDefinitionVersionArn="",
        #     FunctionDefinitionVersionArn=self.state['FunctionDefinition']['LatestVersionArn'],
        #     # LoggerDefinitionVersionArn="",
        #     # SubscriptionDefinitionVersionArn=""
        # )

    def remove_lambdas(self):
        if not (self.state and self.state.get('Lambdas')):
            log.info("There seem to be nothing to remove.")
            return

        log.info("Deleting function definition '{0}' Id='{1}".format(
            self.state['FunctionDefinition']['Name'], self.state['FunctionDefinition']['Id']))
        self._gg.delete_function_definition(
            FunctionDefinitionId=self.state['FunctionDefinition']['Id'])
        self.state.pop('FunctionDefinition')
        _update_state(self.state)

        log.info("Deleting default lambda role '{0}'".format(self.LAMBDA_ROLE_NAME))
        self._remove_default_lambda_role()
        self.state.pop('LambdaRole')
        _update_state(self.state)

        for l in self.state['Lambdas']:
            log.info("Deleting Lambda function '{0}'".format(l['FunctionName']))
            self._lambda.delete_function(FunctionName=l['FunctionName'])
            os.remove(l['ZipPath'])

        self.state.pop('Lambdas')
        _update_state(self.state)

        log.info("Lambdas and function definition deleted OK!")

    def create_subscriptions(self):
        if self.state and self.state.get('Subscriptions'):
            log.warning("Previously created Subscriptions exists. Remove before creating!")
            return
        # MAYBE: don't create subscription before devices and lambdas?

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

        log.info("Creating subscription definition: '{0}'".format(self.name + '_subscription'))
        sub_def = self._gg.create_subscription_definition(
            Name=self.name + '_subscription',
            InitialVersion={'Subscriptions': subs}
        )

        self.state['Subscriptions'] = rinse(sub_def)
        _update_state(self.state)

        sub_def_ver = self._gg.get_subscription_definition_version(
            SubscriptionDefinitionId=self.state['Subscriptions']['Id'],
            SubscriptionDefinitionVersionId=self.state['Subscriptions']['LatestVersion'])

        self.state['Subscriptions']['LatestVersionDetails'] = rinse(sub_def_ver)
        _update_state(self.state)

        log.info("Subscription definition created OK!")

    def remove_subscriptions(self):
        if not (self.state and self.state.get('Subscriptions')):
            log.info("There seem to be nothing to remove.")
            return

        log.info("Deleting subscription definition '{0}' Id='{1}".format(
            self.state['Subscriptions']['Name'], self.state['Subscriptions']['Id']))
        self._gg.delete_subscription_definition(
            SubscriptionDefinitionId=self.state['Subscriptions']['Id'])

        self.state.pop('Subscriptions')
        _update_state(self.state)
        log.info("Subscription definition deleted OK!")

    def _resolve_subscription_destination(self, d):
        p = [x.strip() for x in d.split('::')]
        if p[0] == 'cloud':
            return p[0]
        elif p[0] == 'Lambda':
            return self._lookup_lambda_arn(p[1])
        elif p[0] == 'Device':
            return self._lookup_device_arn(p[1])
        else:
            raise ValueError("Error parsing subscription destination '{0}'. "
                             "Allowed values: 'Lambda::', 'Device::', or 'cloud'.".format(d))

    def _lookup_lambda_arn(self, name):
        # MAYBE: write 'Lambdas' as map for a better lookup?
        #        Or: look up in function definitions function list 'LatestVersionDetails'
        for l in self.state['Lambdas']:
            if l['FunctionName'] == name:
                # TODO:: must be alias!!!
                return l['FunctionArn'] + ':' + self.group['alias']
        log.error("Lambda '{0}' not found".format(name))
        return None

    def _lookup_device_arn(self, name):
        raise NotImplementedError("WIP: Devices not implemented yet.")

    def _create_cores(self):
        # TODO: Refactor-handle state internally, make callable individually
        #       Maybe reflet dependency tree in self.group/greensgo.yaml and travel it
        self.state['Cores'] = []
        cores = []
        initial_version = {'Cores': []}

        for core in self.group['Cores']:
            try:
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

                cores.append({
                    'name': name,
                    'thing': core_thing,
                    'keys': keys_cert,
                    'policy': policy
                })

                self.state['Cores'] = cores
                _update_state(self.state)

                initial_version['Cores'].append({
                    'Id': name,
                    'CertificateArn': keys_cert['certificateArn'],
                    'SyncShadow': core['SyncShadow'],
                    'ThingArn': core_thing['thingArn']
                })

                _save_keys(core['key_path'], name, keys_cert)

                self._create_ggc_config_file(core['config_path'], "config.json", core_thing)

            except Exception as e:
                log.error("Error creating core {0}: {1}".format(name, str(e)))
                # Continue with other cores if any

            log.debug("Creating Core definition with InitialVersion={0}".format(
                initial_version))

            core_def = rinse(self._gg.create_core_definition(
                Name="{0}_core_def".format(self.group['Group']['name']),
                InitialVersion=initial_version
            ))

            log.info("Created Core definition Arn:{0} Id:{1}".format(
                core_def['Arn'], core_def['Id']))

        return core_def, cores

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

    def _create_ggc_config_file(self, path, name, core_thing):

        log.info("Creating GGC config file with core {0} at {1}/{2}".format(
            core_thing['thingName'], path, name))

        config = {
            "coreThing": {
                "caPath": "root.ca.pem",
                "certPath": core_thing['thingName'] + ".pem",
                "keyPath": core_thing['thingName'] + ".key",
                "thingArn": core_thing['thingArn'],
                "iotHost": self._iot_endpoint,
                "ggHost": "greengrass.iot." + self._region + ".amazonaws.com",
                "keepAlive": 600
            },
            "runtime": {
                "cgroup": {
                    "useSystemd": "yes"
                }
            },
            "managedRespawn": False
        }

        _mkdir(path)
        with open(path + '/' + name, 'w') as f:
            json.dump(config, f, indent=4, separators=(',', ' : '))

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
            RoleName=self.LAMBDA_ROLE_NAME,
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
            RoleName=self.LAMBDA_ROLE_NAME,
            PolicyName=self.LAMBDA_ROLE_NAME + "-Policy",
            PolicyDocument=json.dumps(inline_policy))

        return role

    def _remove_default_lambda_role(self):

        for p in self._iam.list_role_policies(RoleName=self.LAMBDA_ROLE_NAME)['PolicyNames']:
            self._iam.delete_role_policy(RoleName=self.LAMBDA_ROLE_NAME, PolicyName=p)

        self._iam.delete_role(RoleName=self.LAMBDA_ROLE_NAME)

###############################################################################
# UTILITY FUNCTIONS


def rinse(boto_response):
    boto_response.pop('ResponseMetadata')
    return boto_response


def pretty(d):
    """Pretty-print object as YAML."""
    print(yaml.safe_dump(d, default_flow_style=False))


def _update_state(group_state):
    if not group_state:
        os.remove(STATE_FILE)
        log.debug("State is empty, removed state file '{0}'".format(STATE_FILE))
        return

    with open(STATE_FILE, 'w') as f:
        json.dump(group_state, f, indent=2,
                  separators=(',', ': '), sort_keys=True, default=str)
        log.debug("Updated group state in state file '{0}'".format(STATE_FILE))


def _state_exists():
    return os.path.exists(STATE_FILE)


def _load_state():
    if not _state_exists():
        log.debug("Group state file {0} not found, assume new group.".format(STATE_FILE))
        return {}
    log.debug("Loading group state from {0}".format(STATE_FILE))
    with open(STATE_FILE, 'r') as f:
        return json.load(f)


def _mkdir(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if not (exc.errno == errno.EEXIST and os.path.isdir(path)):
            raise


def _save_keys(path, name, keys_cert):
    try:
        path = path + '/' if not path.endswith('/') else path
        _mkdir(path)
        certname = path + name + ".pem"
        public_key_file = path + name + ".pub"
        private_key_file = path + name + ".key"
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


def main():
    fire.Fire(GroupCommands)

if __name__ == '__main__':
    main()
