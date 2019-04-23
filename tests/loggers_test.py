import unittest2 as unittest
import yaml
from mock import patch
from .fixtures import BotoSessionFixture, clone_test_state
from greengo import greengo
from greengo.loggers import Loggers

# Do not override the production state, work with testing state.
greengo.STATE_FILE = '.gg_state_test.json'

# For Loggers parameter definitions,
# see https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/greengrass.html#Greengrass.Client.create_logger_definition

greengo_yaml = '''
Group:
    name: my_group
Loggers:
  - Component: Lambda  # 'GreengrassSystem'|'Lambda'
    Id: logger_1       # Arbitrary string
    Level: DEBUG       # 'DEBUG'|'INFO'|'WARN'|'ERROR'|'FATAL'
    Space: 1024        # The amount of file space, in KB, to use if the local file system
    Type: FileSystem   # 'FileSystem'|'AWSCloudWatch'
'''


class LoggersTest(unittest.TestCase):
    def setUp(self):
        self.group = yaml.safe_load(greengo_yaml)
        with patch.object(greengo.session, 'Session', BotoSessionFixture):
            self.gg = greengo.Commands()

    def tearDown(self):
        pass

    def test_loggers_create(self):
        state = clone_test_state()
        state.remove('Loggers')
        l = Loggers(self.group, state)
        l._do_create()
        self.assertTrue(l._gg.create_logger_definition.called)
        self.assertTrue(l._gg.get_logger_definition_version.called)
        self.assertTrue(state.get('Loggers'))

    def test_loggers_remove(self):
        state = clone_test_state()
        l = Loggers(self.group, state)
        l._do_remove()
        self.assertTrue(l._gg.delete_logger_definition.called)

        self.assertFalse(state.get('Loggers'))
