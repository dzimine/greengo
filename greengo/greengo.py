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

logging.basicConfig(
    format='%(asctime)s|%(name).10s|%(levelname).5s: %(message)s',
    level=logging.WARNING)
log = logging.getLogger('greengo')
log.setLevel(logging.DEBUG)


DEFINITION_FILE = 'greengo.yaml'
MAGIC_DIR = '.gg'
STATE_FILE = os.path.join(MAGIC_DIR, 'gg_state.json')

DEPLOY_TIMEOUT = 90  # Timeout, seconds


class Commands(object):
    def __init__(self):

        s = session.Session()
        self._region = s.region_name
        if not self._region:
            log.error("AWS credentials and region must be setup. "
                      "Refer AWS docs at https://goo.gl/JDi5ie")
            exit(-1)

        log.info("AWS credentials found for region '{}'".format(self._region))

        self._gg = s.client("greengrass")
        self._iot = s.client("iot")
        self._lambda = s.client("lambda")
        self._iam = s.client("iam")
        self._iot_endpoint = self._iot.describe_endpoint()['endpointAddress']

        try:
            with open(DEFINITION_FILE, 'r') as f:
                self.group = self.group = yaml.safe_load(f)
        except IOError:
            log.error("Group definition file `greengo.yaml` not found. "
                      "Create file, and define the group definition first. "
                      "See https://github.com/greengo for details.")
            exit(-1)

        self.name = self.group['Group']['name']
        self._LAMBDA_ROLE_NAME = "{0}_Lambda_Role".format(self.name)

    def create(self):
        log.info("[BEGIN] creating group {0}".format(self.group['Group']['name']))

        log.info("[END] creating group {0}".format(self.group['Group']['name']))

    def remove(self):
        log.info("[BEGIN] removing group {0}".format(self.group['Group']['name']))

        log.info("[END] removing group {0}".format(self.group['Group']['name']))

    def create_subscriptions(self, update_group_version=True):
        log.info("Subscription definition created OK!")

    def remove_subscriptions(self):
        log.info("Subscription definition removed OK!")


def main():
    fire.Fire(Commands)

if __name__ == '__main__':
    main()
