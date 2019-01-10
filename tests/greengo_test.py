import os
import shutil
import unittest2 as unittest
import pytest
from mock import patch, MagicMock

from greengo import greengo
from greengo.state import State
from greengo.entity import Entity

# Do not override the production state, work with testing state.
greengo.STATE_FILE = '.gg_state_test.json'
state = None

TEST_KEY_PATH = "tests/certs"
TEST_CONFIG_PATH = "tests/config"


@pytest.fixture(scope="session", autouse=True)
def load_state(request):
    # Load test state once per session.
    global state
    state = greengo.State("tests/test_state.json")
    print("State fixture loaded for testing!")


class SessionFixture():
    region_name = 'moon-darkside'

    def __init__(self):
        global state

        self.greengrass = MagicMock()
        self.greengrass.create_group = MagicMock(
            return_value=state.get('Group'))
        self.greengrass.create_core_definition = MagicMock(
            return_value=state.get('CoreDefinition'))

        subscriptions_return = state.get('Subscriptions').copy()
        subscription_definition_return = subscriptions_return.pop('LatestVersionDetails')

        self.greengrass.create_subscription_definition = MagicMock(
            return_value=subscriptions_return)
        self.greengrass.get_subscription_definition_version = MagicMock(
            return_value=subscription_definition_return)

        self.iot = MagicMock()
        self.iot.create_keys_and_certificate = MagicMock(
            return_value=state.get('Cores')[0]['keys'])
        self.iot.create_thing = MagicMock(
            return_value=state.get('Cores')[0]['thing'])
        self.iot.describe_endpoint = MagicMock(
            return_value={
                'endpointAddress': "foobar.iot.{}.amazonaws.com".format(self.region_name)
            })
        self.iot.create_policy = MagicMock(
            return_value=state.get('Cores')[0]['policy'])

    def client(self, name):
        if name == 'greengrass':
            return self.greengrass
        elif name == 'iot':
            return self.iot

        return MagicMock()


class CommandTest(unittest.TestCase):
    def setUp(self):
        with patch.object(greengo.session, 'Session', SessionFixture):
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
    def test_remove(self, s):
        # Tempted to do greengo.State("tests/test_state.json")?
        # Or use `state`? DONT! `remove` will delete the state fixture file.
        self.gg.state._state = state._state.copy()

        self.gg.remove()

        # TODO: assert that fnctions were called...

    def test_remove__nothing(self):
        self.assertFalse(self.gg.remove())

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
        global state
        # Copy over state and remove Subscriptions
        self.gg.state._state = state._state.copy()
        self.gg.state.remove('Subscriptions')
        self.assertIsNone(self.gg.state.get('Subscriptions'))

        self.gg.create_subscriptions()

        print(self.gg.state.get('Subscriptions'))
        self.assertIsNotNone(self.gg.state.get('Subscriptions'))
        assert self.gg.state.get('Subscriptions') == state.get('Subscriptions')

    # def test_remove_subscriptions(self):
    #     self.gg.remove_subscriptions()


class EntityTest(unittest.TestCase):

    def test_create_group_version__full_state(self):
        global state
        with patch.object(greengo.Entity, '_session', SessionFixture()) as s:
            # Avoid using `state` directly: it'll override the test JSON file.
            ministate = greengo.State(file=None)
            ministate._state = state._state.copy()
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

    def test_create_group_version__empty_state(self):
        with patch.object(greengo.Entity, '_session', SessionFixture()) as s:
            ministate = greengo.State(file=None)
            ministate._state = {'Group': {'Id': '123'}}

            Entity.create_group_version(ministate)

            s.greengrass.create_group_version.assert_called_once_with(
                GroupId='123')

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
