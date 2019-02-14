import os
import fire
import yaml
import logging
import time
from boto3 import session

from __init__ import __version__

from utils import rinse
from .entity import Entity
from state import State
from group import Group
from lambdas import Lambdas
from subscriptions import Subscriptions

log = logging.getLogger(__name__)

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
        self._session = s
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

    def state(self):
        print(self.state)

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

        Subscriptions(self.group, self.state).remove(update_group_version=False)

        Lambdas(self.group, self.state).remove(update_group_version=False)

        # Remove other entities here, before removing Group.

        Group(self.group, self.state).remove(update_group_version=False)

        self.state.remove()

        log.info("[END] removing group {0}".format(self.group['Group']['name']))

    def create_group(self):
        Group(self.group, self.state).create()

    def remove_group(self):
        Group(self.group, self.state).remove()

    def create_lambdas(self):
        Lambdas(self.group, self.state).create()

    def remove_lambdas(self):
        Lambdas(self.group, self.state).remove()

    def create_subscriptions(self):
        Subscriptions(self.group, self.state).create()

    def remove_subscriptions(self):
        Subscriptions(self.group, self.state).remove()

    def deploy(self):
        if not self.state:
            log.info("There is nothing to deploy. Do create first.")
            return

        log.info("Deploying group '{0}'".format(self.state.get('Group.Name')))
        gg = self._session.client("greengrass")
        deployment = gg.create_deployment(
            GroupId=self.state.get('Group.Id'),
            GroupVersionId=self.state.get('Group.Version.Version'),
            DeploymentType="NewDeployment")
        self.state.update('Deployment', rinse(deployment))

        for i in range(DEPLOY_TIMEOUT / 2):
            time.sleep(2)
            deployment_status = gg.get_deployment_status(
                GroupId=self.state.get('Group.Id'),
                DeploymentId=deployment['DeploymentId'])

            status = deployment_status.get('DeploymentStatus')

            log.debug("--- deploying... status: {0}".format(status))
            # Known status values: ['Building | InProgress | Success | Failure']
            if status == 'Success':
                log.info("--- SUCCESS!")
                self.state.update('Deployment.Status', rinse(deployment_status))
                return
            elif status == 'Failure':
                log.error("--- ERROR! {0}".format(deployment_status['ErrorMessage']))
                self.state.update('Deployment.Status', rinse(deployment_status))
                return

        log.warning(
            "--- Gave up waiting for deployment. Please check the status later. "
            "Make sure GreenGrass Core is running, connected to network, "
            "and the certificates match.")


def main():
    logging.basicConfig(
        format='%(asctime)s|%(name).10s|%(levelname).5s: %(message)s',
        level=logging.WARNING)
    logging.getLogger('greengo').setLevel(logging.DEBUG)
    logging.getLogger('__main__').setLevel(logging.DEBUG)  # There is a beter way...
    fire.Fire(Commands)

if __name__ == '__main__':
    main()
