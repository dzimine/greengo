import copy
from mock import MagicMock
from greengo.state import State

state = State("tests/test_state.json")


def clone_test_state():
    global state
    s = State(file=None)
    s._state = copy.deepcopy(state._state)
    return s


class BotoSessionFixture():
    region_name = 'moon-darkside'

    def __init__(self):
        # MAYBE: move to a method and get state clone with clone_test_state every time?
        state = clone_test_state()

        self.greengrass = MagicMock()
        self.greengrass.create_group = MagicMock(
            return_value=state.get('Group'))
        self.greengrass.create_core_definition = MagicMock(
            return_value=state.get('CoreDefinition'))

        subscription_def_return = state.get('Subscriptions').copy()
        subscription_def_version_return = subscription_def_return.pop('LatestVersionDetails')

        self.greengrass.create_subscription_definition = MagicMock(
            return_value=subscription_def_return)
        self.greengrass.get_subscription_definition_version = MagicMock(
            return_value=subscription_def_version_return)

        resource_def_return = state.get('Resources').copy()
        resource_def_version_return = resource_def_return.pop('LatestVersionDetails')

        self.greengrass.create_resource_definition = MagicMock(
            return_value=resource_def_return)
        self.greengrass.get_resource_definition_version = MagicMock(
            return_value=resource_def_version_return)

        function_definition_return = state.get('Lambdas.FunctionDefinition')
        function_definition_version_return = function_definition_return.pop('LatestVersionDetails')

        self.greengrass.create_function_definition = MagicMock(
            return_value=function_definition_return)

        self.greengrass.get_function_definition_version = MagicMock(
            return_value=function_definition_version_return)

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

        self._lambda = MagicMock()
        self._lambda.create_function = MagicMock(return_value=state.get('Lambdas.Functions')[0])
        self._lambda.create_alias = MagicMock(
            return_value={
                'FunctionVersion': state.get('Lambdas.Functions')[0]['Version'],
                'AliasArn': state.get('Lambdas.Functions')[0]['FunctionArn'],
            })

        self.iam = MagicMock()
        self.iam.create_role = MagicMock(return_value=state.get('Lambdas.LambdaRole'))

    def client(self, name):
        if name == 'greengrass':
            return self.greengrass
        elif name == 'iot':
            return self.iot
        elif name == 'lambda':
            return self._lambda
        elif name == 'iam':
            return self.iam

        return MagicMock()
