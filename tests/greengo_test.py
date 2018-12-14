import os
import unittest
import pytest
from mock import patch, MagicMock

from greengo import greengo

# Do not override the production state, work with testing state.
greengo.STATE_FILE = '.gg_state_test.json'
state = None


@pytest.fixture(scope="session", autouse=True)
def load_state(request):
    # Load test state once per session.
    global state
    state = greengo.State("tests/test_state.json")


class SessionFixture():
    region_name = 'moon-darkside'

    def __init__(self):
        self.mock = MagicMock()
        self.mock.describe_endpoint = MagicMock(
            return_value={'endpointAddress': "xxx.iot.moon-darkside.amazonaws.com"})

        self.greengrass = MagicMock()
        self.greengrass.create_group = MagicMock(
            return_value=state.get('Group'))

    def client(self, name):
        if name == 'greengrass':
            return self.greengrass
        return MagicMock()


class CommandTest(unittest.TestCase):
    def setUp(self):
        with patch.object(greengo.session, 'Session', SessionFixture):
            self.gg = greengo.Commands()

    def tearDown(self):
        try:
            os.remove(greengo.STATE_FILE)
        except OSError:
            pass

    def test_create__all_new(self):
        self.assertFalse(self.gg.state.get(), "State must be empty first")

        self.gg.create()
        # print(self.gg.state.get())

        self.assertIsNotNone(self.gg.state.get('Group'))
        self.assertIsNotNone(self.gg.state.get('Subscriptions'))

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
