import logging
import json
import time
from botocore.exceptions import ClientError

from entity import Entity
from utils import rinse, mkdir, save_keys

log = logging.getLogger(__name__)


class Group(Entity):

    def __init__(self, group, state):
        super(Group, self).__init__(group, state)
        self.type = 'Group'
        self.name = group['Group']['name']

        self._region = Entity._session.region_name
        self._gg = Entity._session.client("greengrass")
        self._iot = Entity._session.client("iot")
        # self._lambda = s.client("lambda")
        # self._iam = s.client("iam")
        self._iot_endpoint = self._iot.describe_endpoint()['endpointAddress']

    def _do_create(self):
        log.info("Creating group '{}'".format(self._group['Group']['name']))

        g = rinse(self._gg.create_group(Name=self.name))
        self._state.update(self.type, g)

        self._create_cores()

    def _do_remove(self):

        log.info("Reseting deployments forcefully, if they exist")
        # print(json.dumps(self._state._state['Group'], indent=4, default=str))
        self._gg.reset_deployments(GroupId=self._state.get('Group.Id'), Force=True)

        self._remove_cores()

        log.info("Deleting group '{0}'".format(self._state.get('Group.Id')))
        self._gg.delete_group(GroupId=self._state.get('Group.Id'))

    def _create_cores(self):
        # Design notes:
        # 1) In practice one Group has only one Core. But AWS model implies one-to-many relations.
        #    I go for the model.
        # 2) It might be proper to make Cores a separate Entity. But Group and Core are tightly
        #    coupled, always created/removed together and can't be used independent of each other.
        #    Thus I keep them in the same class.
        cores = []
        initial_version = {'Cores': []}

        for core in self._group['Cores']:
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
                    policy_doc=self._get_core_policy_doc(),
                    thing_cert_arn=keys_cert['certificateArn']
                )

                cores.append({
                    'name': name,
                    'thing': core_thing,
                    'keys': keys_cert,
                    'policy': policy
                })

                self._state.update('Cores', cores)

                initial_version['Cores'].append({
                    'Id': name,
                    'CertificateArn': keys_cert['certificateArn'],
                    'SyncShadow': core['SyncShadow'],
                    'ThingArn': core_thing['thingArn']
                })

                save_keys(core['key_path'], name, keys_cert)

                self._create_ggc_config_file(core['config_path'], "config.json", core_thing)

            except Exception as e:
                log.error("Error creating core {0}: {1}".format(name, str(e)))
                raise

            log.debug("Creating Core definition with InitialVersion={0}".format(
                initial_version))

            core_def = rinse(self._gg.create_core_definition(
                Name="{0}_core_def".format(self._group['Group']['name']),
                InitialVersion=initial_version
            ))

            self._state.update('CoreDefinition', core_def)

            log.info("Created Core definition Arn:{0} Id:{1}".format(
                core_def['Arn'], core_def['Id']))

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

    def _get_core_policy_doc(self):
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
                "caPath": "root-CA.crt",
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

        mkdir(path)
        with open(path + '/' + name, 'w') as f:
            json.dump(config, f, indent=4, separators=(',', ' : '))

    def _remove_cores(self):

        for core in self._state.get('Cores'):
            try:
                thing_name = core['thing']['thingName']
                cert_id = core['keys']['certificateId']
                log.info("Removing core thing '{0}'' from core '{1}'".format(
                    thing_name, core['name']))

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

                log.debug(
                    "--- taking 1 sec. nap as a superstition to let certificate update propagate...")
                time.sleep(1)

                log.debug("--- deleting certificate: '{0}'".format(core['keys']['certificateId']))
                self._iot.delete_certificate(certificateId=core['keys']['certificateId'])

                log.debug("--- deleting thing: '{0}'".format(core['thing']['thingName']))
                self._iot.delete_thing(thingName=core['thing']['thingName'])

            except Exception as e:
                log.error("Error removing core {0}: {1}".format(core['name'], str(e)))

        self._state.remove('Cores')
        log.info("Cores removed OK!")

        core_def = self._state.get('CoreDefinition')
        log.info("Removing core definition '{0}'".format(core_def['Name']))
        self._gg.delete_core_definition(CoreDefinitionId=core_def['Id'])

        self._state.remove('CoreDefinition')
        log.info("Core definition '{0}' removed OK!".format(core_def['Name']))
