import unittest2 as unittest
import yaml
from mock import patch, MagicMock
import logging
from botocore.exceptions import ClientError

from fixtures import BotoSessionFixture, clone_test_state
from greengo import greengo
from greengo.lambdas import Lambdas
from greengo.state import State

logging.basicConfig(
    format='%(asctime)s|%(name).10s|%(levelname).5s: %(message)s',
    level=logging.DEBUG)

# Do not override the production state, work with testing state.
greengo.STATE_FILE = '.gg_state_test.json'

lambdas_yaml = '''
Group:
    name: my_group
Lambdas:
  - name: GreengrassHelloWorld
    runtime: Python2.7
    handler: function.handler
    package: lambdas/GreengrassHelloWorld
    alias: dev
    environment:
      foo: bar
    greengrassConfig:
      MemorySize: 128000 # Kb, ask AWS why
      Timeout: 10 # Sec
      Pinned: True # Set True for long-lived functions
      Environment:
        AccessSysfs: False
        ResourceAccessPolicies:
          - ResourceId: 1_path_to_input
            Permission: 'rw'
        Variables:
           name: value
'''


class LambdasTest(unittest.TestCase):
    def setUp(self):
        with patch.object(greengo.session, 'Session', BotoSessionFixture) as f:
            self.boto_session = f
            self.gg = greengo.Commands()

    def tearDown(self):
        pass

    def test_lambda_create(self):
        group = yaml.load(lambdas_yaml)
        state = clone_test_state()
        state.remove('Lambdas')
        Lambdas(group, state)._do_create()

    def test_default_lambda_role_arn__already_created(self):
        group = yaml.load(lambdas_yaml)
        state = clone_test_state()
        arn = Lambdas(group, state)._default_lambda_role_arn()
        self.assertEqual(arn, state.get('LambdaRole.Role.Arn'))

    def test_default_lambda_role_arn__create(self):
        group = yaml.load(lambdas_yaml)
        arn = clone_test_state().get('LambdaRole.Role.Arn')
        state = State(file=None)
        arn = Lambdas(group, state)._default_lambda_role_arn()
        self.assertEqual(arn, state.get('LambdaRole.Role.Arn'))

    def test_default_lambda_role_arn__previously_defined(self):
        group = yaml.load(lambdas_yaml)
        la = Lambdas(group, State(file=None))
        error = ClientError(
            error_response={'Error': {'Code': 'EntityAlreadyExists'}},
            operation_name='CreateRole')

        la._iam.create_role = MagicMock(side_effect=error)
        arn = la._default_lambda_role_arn()  # Doesn't blow up
        self.assertIsNotNone(arn)
