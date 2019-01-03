import os
import shutil
import unittest
import pytest
from mock import patch, MagicMock

from greengo import greengo
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

    def test_create__all_new(self):
        self.assertFalse(self.gg.state.get(), "State must be empty first")

        self.gg.create()

        # print(self.gg.state.get())

        self.assertIsNotNone(self.gg.state.get('Group'))
        self.assertIsNotNone(self.gg.state.get('Cores'))
        self.assertIsNotNone(self.gg.state.get('CoreDefinition'))
        self.assertIsNotNone(self.gg.state.get('Subscriptions'))

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

    def test_remove(self):
        # Tempted to do greengo.State("tests/test_state.json")?
        # Or use `state`? DONT! `remove` will delete the state fixture file.
        self.gg.state._state = state._state.copy()

        self.gg.remove()

    def test_remove__nothing(self):
        self.assertFalse(self.gg.remove())

    # def test_create_subscriptions(self):
    #     self.gg.create_subscriptions()

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
