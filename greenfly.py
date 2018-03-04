import os
import errno
import fire
import json
import yaml
from time import sleep
import logging
from boto3.session import Session
from botocore.exceptions import ClientError

logging.basicConfig(
    format='%(asctime)s|%(name)-8s|%(levelname)s: %(message)s',
    level=logging.INFO)
log = logging.getLogger('iot-greengrass')
log.setLevel(logging.DEBUG)


STATE_FILE = '.group_state.json'


class GroupCommands(object):
    def __init__(self):
        super(GroupCommands, self).__init__()

        session = Session()
        self._gg = session.client("greengrass")
        self._iot = session.client("iot")
        self._region = session.region_name
        self._iot_endpoint = self._iot.describe_endpoint()['endpointAddress']

        with open('group.yaml', 'r') as f:
            self.group = self.group = yaml.safe_load(f)

        self.state = _load_state()

    def create(self):
        if self.state:
            log.error("Previously created group exists. Remove before creating!")
            return False

        log.info("[BEGIN] creating group {0}".format(self.group['name']))

        # 1. Create group
        # TODO: create group at the end, with "initial version"?
        group = rinse(self._gg.create_group(Name=self.group['name']))
        self.state['Group'] = group
        _update_state(self.state)
        # Must update state on every step, else how can I clean?
        # Or on exception?

        # 2. Create core a) thing b) attach to group
        core_def, cores = self._create_cores()
        self.state['Cores'] = cores
        self.state['CoreDefinition'] = core_def
        _update_state(self.state)

        # LAST. Add all the constituent parts to the Greengrass Group
        group_ver = rinse(self._gg.create_group_version(
            GroupId=group['Id'],
            CoreDefinitionVersionArn=core_def['LatestVersionArn']
            # DeviceDefinitionVersionArn="",
            # FunctionDefinitionVersionArn="",
            # LoggerDefinitionVersionArn="",
            # SubscriptionDefinitionVersionArn=""
        ))

        self.state['Group']['Version'] = group_ver
        _update_state(self.state)

        log.info("[END] creating group {0}".format(self.group['name']))

    def remove(self):
        if not self.state:
            log.info("There seem to be nothing to remove.")
            return

        log.info("[BEGIN] removing group {0}".format(self.group['name']))

        self._remove_cores()

        self._gg.delete_group(GroupId=self.state['Group']['Id'])

        os.remove(STATE_FILE)

        log.info("[END] removing group {0}".format(self.group['name']))

    def _create_cores(self):
        self.state['Cores'] = []
        cores = []
        initial_version = {'Cores': []}

        for core in self.group['Cores']:
            try:
                name = core['name']
                log.info("Creating a thing for core {0}".format(name))
                keys_cert = rinse(self._iot.create_keys_and_certificate(setAsActive=True))
                core_thing = rinse(self._iot.create_thing(thingName=name))
                # (dzimine) This saved my ass when cleaning up
                self._iot.update_thing(
                    thingName=name,
                    attributePayload={
                        'attributes': {
                            'thingArn': core_thing['thingArn'],
                            'certificateId': keys_cert['certificateId']
                        },
                        'merge': True
                    }
                )
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

                # XXX: Temp - record on each step. Refactor!!!
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
                Name="{0}_core_def".format(self.group['name']),
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
            log.info("Removing core thing {0} from core {1}".format(
                core['name'], thing_name))

            log.debug('--- detaching policy: {0}'.format(core['policy']['policyName']))
            self._iot.detach_principal_policy(
                policyName=core['policy']['policyName'], principal=core['keys']['certificateArn'])

            log.debug('--- deleting policy:{0}'.format(core['policy']['policyName']))
            self._iot.delete_policy(policyName=core['policy']['policyName'])

            log.debug('--- deactivating certificate: {0}'.format(core['keys']['certificateId']))
            self._iot.update_certificate(
                certificateId=cert_id, newStatus='INACTIVE')

            log.debug('--- detaching certificate:{0} from thing:{1}'.format(cert_id, thing_name))
            self._iot.detach_thing_principal(
                thingName=thing_name, principal=core['keys']['certificateArn'])
            sleep(1)

            log.debug('--- deleting certificate: {0}'.format(core['keys']['certificateId']))
            self._iot.delete_certificate(certificateId=core['keys']['certificateId'])

            log.debug('--- deleting thing: {0}'.format(core['thing']['thingName']))
            self._iot.delete_thing(thingName=core['thing']['thingName'])

        core_def = self.state['CoreDefinition']
        log.info("Removing core definition {0}".format(core_def['Name']))
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
        # TODO: redo as template and read from group.yaml
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


###############################################################################
# UTILITY FUNCTIONS


def rinse(boto_response):
    response = boto_response.pop('ResponseMetadata')
    log.debug("HTTP Status: {0}".format(response['HTTPStatusCode']))
    return boto_response


def _update_state(group_state):
    with open(STATE_FILE, 'w') as f:
        json.dump(group_state, f, indent=2,
                  separators=(',', ': '), sort_keys=True)
        log.debug("Updated group state in state file: {0}".format(STATE_FILE))


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
