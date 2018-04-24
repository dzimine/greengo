import os
import json
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
    with open('tests/test_state.json', 'r') as f:
        state = greengo.State(json.load(f))


class SessionFixture():
    region_name = 'moon-darkside'

    def __init__(self):
        self.mock = MagicMock()
        self.mock.describe_endpoint = MagicMock(
            return_value={'endpointAddress': "xxx.iot.moon-darkside.amazonaws.com"})

    def client(self, name):
        return self.mock


def rinse(d):
    # Overriding greengo.rinse so it won't give `KeyError` for missed `ResponseMetadata`
    return d


@patch('greengo.greengo.rinse', rinse)
class GroupCommandTest(unittest.TestCase):

    def setUp(self):
        with patch.object(greengo.session, 'Session', SessionFixture):
            self.gg = greengo.GroupCommands()

    def tearDown(self):
        try:
            os.remove(greengo.STATE_FILE)
        except OSError:
            pass

    def test_main(self):
        print self.gg
        pass

    def test_create_subscriptions(self):
        self.gg.state = greengo.State(state.copy())
        self.gg.state.pop('Subscriptions')
        self.gg._gg.create_subscription_definition = MagicMock(return_value=state['Subscriptions'])
        self.gg._gg.get_subscription_definition_version = MagicMock(
            return_value=state['Subscriptions']['LatestVersionDetails'])

        self.gg.create_subscriptions()
        # TODO: assert calls

    def test_create_subscriptions_empty(self):
        self.gg.group.pop('Subscriptions')
        self.gg.create_subscriptions()

    def test_remove_subscriptions(self):
        self.gg._gg.delete_subscription_definition = MagicMock(return_value=state['Subscriptions'])
        self.gg.state = greengo.State(state.copy())

        self.gg.remove_subscriptions()
        self.assertFalse(self.gg.state.get('Subscriptions'), "Subscriptions shall be removed")
        greengo.pretty(state['Subscriptions'])

    def test_create_group_version_fullset(self):
        self.gg.state = greengo.State(state.copy())

        m = MagicMock()
        self.gg._gg.create_group_version = m
        self.gg.create_group_version()

        args, kwargs = m.call_args
        self.assertEqual(len(kwargs), 4)  # TODO: Refine expected kwarg count

    def test_create_group_version_subset(self):
        self.gg.state = greengo.State(state.copy())
        self.gg.state.pop('Subscriptions')
        self.gg.state.pop('FunctionDefinition')

        m = MagicMock()
        self.gg._gg.create_group_version = m
        self.gg.create_group_version()

        args, kwargs = m.call_args
        self.assertEqual(len(kwargs), 2)  # TODO: Refine expected kwarg count


@patch('greengo.greengo.rinse', rinse)
class LambdaTest(unittest.TestCase):

    def setUp(self):
        with patch.object(greengo.session, 'Session', SessionFixture):
            self.gg = greengo.GroupCommands()

    def tearDown(self):
        try:
            os.remove(greengo.STATE_FILE)
        except OSError:
            pass

    def test_create_lambdas_empty(self):
        self.gg.group.pop('Lambdas')
        self.gg.create_lambdas()  # Doesn't blow up
