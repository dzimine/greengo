import os
import shutil
import unittest2 as unittest
from mock import patch
from fixtures import BotoSessionFixture, clone_test_state

from greengo import greengo
from greengo.state import State
from greengo.entity import Entity

# Do not override the production state, work with testing state.
greengo.STATE_FILE = '.gg_state_test.json'

TEST_KEY_PATH = "tests/certs"
TEST_CONFIG_PATH = "tests/config"


class CommandTest(unittest.TestCase):
    def setUp(self):
        with patch.object(greengo.session, 'Session', BotoSessionFixture):
            self.gg = greengo.Commands()
        self.gg.group['Cores'][0]['key_path'] = TEST_KEY_PATH
        self.gg.group['Cores'][0]['config_path'] = TEST_CONFIG_PATH
        self.core_name = self.gg.group['Cores'][0]['name']

    def tearDown(self):
        try:
            os.remove(greengo.STATE_FILE)
            shutil.rmtree(TEST_KEY_PATH)
            shutil.rmtree(TEST_CONFIG_PATH)
        except OSError:
            pass

    @patch('time.sleep', return_value=None)
    def test_create__all_new(self, s):
        self.assertFalse(self.gg.state.get(), "State must be empty first")

        self.gg.create()

        # print(self.gg.state.get())

        self.assertIsNotNone(self.gg.state.get('Group'))
        self.assertIsNotNone(self.gg.state.get('Cores'))
        self.assertIsNotNone(self.gg.state.get('CoreDefinition'))
        self.assertIsNotNone(self.gg.state.get('Subscriptions'))
        self.assertIsNotNone(self.gg.state.get('Group.Version'))

        # Check that cert and config files have been created
        self.assertTrue(
            os.path.isfile(os.path.join(TEST_KEY_PATH, "{}.pem".format(self.core_name))))
        self.assertTrue(
            os.path.isfile(os.path.join(TEST_KEY_PATH, "{}.pub".format(self.core_name))))
        self.assertTrue(
            os.path.isfile(os.path.join(TEST_KEY_PATH, "{}.key".format(self.core_name))))
        self.assertTrue(
            os.path.isfile(os.path.join(TEST_CONFIG_PATH, "config.json")))

    def test_create__alredy_created(self):
        # Create a state that isn't empty
        self.gg.state.update('foo', {})

        r = self.gg.create()

        self.assertFalse(r)

    @patch('time.sleep', return_value=None)
    def test_remove__all(self, s):
        # Tempted to do greengo.State("tests/test_state.json")?
        # DONT! `remove` will delete the state fixture file.
        self.gg.state = clone_test_state()

        self.gg.remove()

        self.assertFalse(self.gg.state.get())

        # Assert that SOME entities were removed
        gg = greengo.Entity._session.greengrass
        iot = greengo.Entity._session.iot
        # Lambdas
        self.assertTrue(gg.delete_function_definition.called)
        # Subscriptions
        self.assertTrue(gg.delete_subscription_definition.called)
        # Core
        self.assertTrue(gg.delete_core_definition.called)
        self.assertTrue(iot.delete_thing)
        # Group
        self.assertTrue(gg.delete_group.called)

    def test_remove__nothing(self):
        self.assertFalse(self.gg.remove())

    @patch('time.sleep', return_value=None)
    def test_deploy__success(self, s):
        self.gg.state = clone_test_state()

        gg = self.gg._session.greengrass
        gg.create_deployment.return_value = {'DeploymentId': '123'}
        gg.get_deployment_status.return_value = {'DeploymentStatus': 'Success'}
        self.gg.deploy()

        self.assertTrue(gg.create_deployment.called)
        self.assertEqual(self.gg.state.get('Deployment.Status.DeploymentStatus'), 'Success')

    @patch('time.sleep', return_value=None)
    def test_deploy__error(self, s):
        self.gg.state = clone_test_state()

        gg = self.gg._session.greengrass
        gg.get_deployment_status.side_effect = (
            {'DeploymentStatus': 'Building'},
            {'DeploymentStatus': 'InProgress'},
            {'DeploymentStatus': 'Failure', 'ErrorMessage': "Mock error"}
        )
        self.gg.deploy()

    @patch('greengo.subscriptions.Subscriptions._do_create')
    def test_create_subscriptions__no_group(self, fm):
        with self.assertLogs('greengo.entity', level='WARNING') as l:
            self.gg.create_subscriptions()
            self.assertFalse(fm.called)
            self.assertTrue("Group must be created before Subscriptions" in '\n'.join(l.output))

    @patch('greengo.subscriptions.Subscriptions._do_create')
    def test_create_subscriptions__not_defined(self, fm):
        self.gg.group.pop('Subscriptions')
        with self.assertLogs('greengo.entity', level='WARNING') as l:
            self.gg.create_subscriptions()

            self.assertFalse(fm.called)
            self.assertTrue("skipping" in '\n'.join(l.output))

    @patch('greengo.subscriptions.Subscriptions._do_create')
    def test_create_subscriptions__already_created(self, fm):
        # Pretend that it's already created
        self.gg.state.update('Group', "not_empty")
        self.gg.state.update('Subscriptions', "not_empty")

        with self.assertLogs('greengo.entity', level='WARNING') as l:
            self.gg.create_subscriptions()

            self.assertFalse(fm.called)
            self.assertTrue("already created" in '\n'.join(l.output))

    def test_create_subscriptions__create(self):
        # Copy over state and remove Subscriptions
        self.gg.state = clone_test_state()
        self.gg.state.remove('Subscriptions')
        self.assertIsNone(self.gg.state.get('Subscriptions'))

        self.gg.create_subscriptions()

        expected_state = clone_test_state()
        self.assertIsNotNone(self.gg.state.get('Subscriptions'))
        assert self.gg.state.get('Subscriptions') == expected_state.get('Subscriptions')

    @patch('greengo.subscriptions.Subscriptions._do_remove')
    def test_remove_subscriptions__missing(self, fm):
        # Copy over state and remove Subscriptions
        self.gg.state = clone_test_state()
        self.gg.state.remove('Subscriptions')
        self.assertIsNone(self.gg.state.get('Subscriptions'))

        with self.assertLogs('greengo.entity', level='WARNING') as l:
            self.gg.remove_subscriptions()

            self.assertFalse(fm.called)
            self.assertTrue("does not exist" in '\n'.join(l.output))

    def test_remove_subscriptions(self):
        self.gg.state = clone_test_state()
        expected_id = self.gg.state.get('Subscriptions.Id')

        self.gg.remove_subscriptions()
        self.assertIsNone(self.gg.state.get('Subscriptions'))
        print Entity._session.greengrass.delete_subscription_definition.assert_called_once_with(
            SubscriptionDefinitionId=expected_id)


class EntityTest(unittest.TestCase):

    def test_create_group_version__full_state(self):
        with patch.object(greengo.Entity, '_session', BotoSessionFixture()) as s:
            ministate = clone_test_state()
            Entity.create_group_version(ministate)

            s.greengrass.create_group_version.assert_called_once()
            args, kwargs = s.greengrass.create_group_version.call_args
            expected_keys = [
                'GroupId',
                'CoreDefinitionVersionArn',
                'FunctionDefinitionVersionArn',
                'SubscriptionDefinitionVersionArn',
                'LoggerDefinitionVersionArn',
                'ResourceDefinitionVersionArn',
                'ConnectorDefinitionVersionArn',
                # 'DeviceDefinitionVersionArn'  # NOT IMPLEMENTED
            ]
            self.assertEqual(set(expected_keys), set(kwargs.keys()))

    def test_create_group_version__state_group_only(self):
        with patch.object(greengo.Entity, '_session', BotoSessionFixture()) as s:
            ministate = greengo.State(file=None)
            ministate._state = {'Group': {'Id': '123'}}

            Entity.create_group_version(ministate)

            s.greengrass.create_group_version.assert_called_once_with(
                GroupId='123')

    def test_create_group_version__empty_state(self):
        with self.assertLogs('greengo.entity', level='DEBUG') as l:

            ministate = greengo.State(file=None)
            Entity.create_group_version(ministate)
            output = '\n'.join(l.output)
            assert "Attempting to update group version" in output

    @patch('greengo.entity.Entity._do_create')
    def test_create_entity__missed_requirements(self, fm):
        e = Entity({'Entity': "something"}, State(file=None))
        e.type = "Entity"
        e._requirements = ['Group', 'Lambdas']
        with self.assertLogs('greengo.entity', level='WARNING') as l:
            e.create()
            self.assertFalse(fm.called)
            output = '\n'.join(l.output)
            assert "Group" in output
            assert "Lambdas" in output
