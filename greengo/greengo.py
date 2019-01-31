import os
import fire
import yaml
# import shutil
# import urllib
import logging
from boto3 import session
# from botocore.exceptions import ClientError

from __init__ import __version__

from entity import Entity
from state import State
from group import Group
from lambdas import Lambdas
from subscriptions import Subscriptions

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

        Entity._session = s
        # self._iot_endpoint = s.client("iot").describe_endpoint()['endpointAddress']

        try:
            with open(DEFINITION_FILE, 'r') as f:
                self.group = yaml.safe_load(f)
        except IOError:
            log.error("Group definition file `greengo.yaml` not found. "
                      "Create file, and define the group definition first. "
                      "See https://github.com/greengo for details.")
            exit(-1)

        self.state = State(STATE_FILE)

        self.name = self.group['Group']['name']

    def version(self):
        print('Greengo version {}'.format(__version__))

    def create(self):
        if self.state.get():
            log.error("Previously created group exists. Remove before creating!")
            return False

        log.info("[BEGIN] creating group {0}".format(self.group['Group']['name']))

        Group(self.group, self.state).create(update_group_version=False)

        Lambdas(self.group, self.state).create(update_group_version=False)

        Subscriptions(self.group, self.state).create(update_group_version=False)

        # Create other entities like this...

        Group.create_group_version(self.state)

        log.info("[END] creating group {0}".format(self.group['Group']['name']))

    def remove(self):
        if not self.state.get():
            log.info("There seem to be nothing to remove.")
            return False

        log.info("[BEGIN] removing group {0}".format(self.group['Group']['name']))

        Group(self.group, self.state).remove()

        self.state.remove()

        log.info("[END] removing group {0}".format(self.group['Group']['name']))

    def create_group(self):
        NotImplementedError

    def remove_group(self):
        NotImplementedError

    def create_lambdas(self, update_group_version=True):
        Lambdas(self.group, self.state).create(update_group_version=True)

    def create_subscriptions(self, update_group_version=True):
        Subscriptions(self.group, self.state).create(update_group_version=True)

    def remove_lambdas(self):
        raise NotImplementedError

    def remove_subscriptions(self):
        Subscriptions(self.group, self.state).remove()


def main():
    fire.Fire(Commands)

if __name__ == '__main__':
    main()
