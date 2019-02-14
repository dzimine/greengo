import unittest2 as unittest
import yaml
from mock import patch

from fixtures import BotoSessionFixture, clone_test_state
from greengo import greengo
from greengo.subscriptions import Subscriptions

# Do not override the production state, work with testing state.
greengo.STATE_FILE = '.gg_state_test.json'

greengo_yaml = '''
Group:
    name: my_group
Subscriptions:
  - Source: Lambda::GreengrassHelloWorld
    Subject: lambda2cloud
    Target: cloud
  - Source: cloud
    Subject: cloud2lambda
    Target: Lambda::GreengrassHelloWorld
  - Source: cloud
    Subject: cloud2connector
    Target: Connector::ModbusProtocolAdapterConnector
  - Source: GGShadowService
    Subject: shadow2cloud
    Target: cloud
'''

ministate = {
    "Connectors": {
        "Arn": "arn:aws:greengrass:us-west-2:000000000000:/greengrass/definition/connectors/0000",
        "LatestVersionDetails": {
            "Definition": {
                "Connectors": [{
                    "ConnectorArn": "arn:aws:greengrass:us-west-2::/connectors/XXXXX",
                    "Id": "ModbusProtocolAdapterConnector"

                }]
            },
        },
        "Name": "Modbus-greengate_connectors"
    },
    "Lambdas": [
        {
            "FunctionArn": "arn:aws:lambda:us-west-2:000000000000:function:GreengrassHelloWorld",
            "FunctionName": "GreengrassHelloWorld",
        }
    ],
}


class SubscriptionsTest(unittest.TestCase):
    '''
    Subscription's `create` and `remove` are tested in greengo_test.
    Here comes extra tests for elaborate private methods.
    '''
    def setUp(self):
        with patch.object(greengo.session, 'Session', BotoSessionFixture):
            self.gg = greengo.Commands()

    def tearDown(self):
        pass

    def test_resolve_subscription_destionation(self):
        group = yaml.load(greengo_yaml)
        s = Subscriptions(group, clone_test_state())

        self.assertEqual(
            s._resolve_subscription_destination("Connector::ModbusProtocolAdapterConnector"),
            s._state.get('Connectors.LatestVersionDetails.Definition.Connectors')[0]['ConnectorArn']
        )

        self.assertEqual(
            s._resolve_subscription_destination("Lambda::GreengrassHelloWorld"),
            s._state.get('FunctionDefinition.LatestVersionDetails.Definition.Functions')[0]['FunctionArn']
        )

        self.assertEqual(
            s._resolve_subscription_destination("cloud"),
            "cloud"
        )

        self.assertEqual(
            s._resolve_subscription_destination("GGShadowService"),
            "GGShadowService"
        )
