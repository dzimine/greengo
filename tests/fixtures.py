from mock import MagicMock
from greengo.state import State

state = State("tests/test_state.json")


def clone_test_state():
    global state
    s = State(file=None)
    s._state = state._state.copy()
    return s


class BotoSessionFixture():
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
