import unittest2 as unittest
import yaml
from mock import patch

from .fixtures import BotoSessionFixture, clone_test_state
from greengo import greengo
from greengo.resources import Resources

# Do not override the production state, work with testing state.
greengo.STATE_FILE = '.gg_state_test.json'

greengo_yaml = '''
Group:
    name: my_group
Resources:
  - Name: path_to_input
    Id: resource_1_path_to_input
    LocalVolumeResourceData:
      SourcePath: /images
      DestinationPath: /input
      GroupOwnerSetting:
        AutoAddGroupOwner: True
'''


class ResourcesTest(unittest.TestCase):

    def setUp(self):
        self.group = yaml.safe_load(greengo_yaml)
        with patch.object(greengo.session, 'Session', BotoSessionFixture):
            self.gg = greengo.Commands()

    def tearDown(self):
        pass

    def test_resources_create(self):
        state = clone_test_state()
        state.remove('Resources')
        r = Resources(self.group, state)
        r._do_create()
        self.assertTrue(r._gg.create_resource_definition.called)
        self.assertTrue(r._gg.get_resource_definition_version.called)
        self.assertTrue(state.get('Resources'))

    def test_resources_remove(self):
        state = clone_test_state()
        r = Resources(self.group, state)
        r._do_remove()
        self.assertFalse(state.get('Resources'))
