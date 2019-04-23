import logging

from .utils import pretty, rinse
from .entity import Entity

log = logging.getLogger(__name__)


class Resources(Entity):

    def __init__(self, group, state):
        super(Resources, self).__init__(group, state)
        self.type = 'Resources'
        self.name = group['Group']['name'] + '_resources'

        self._requirements = ['Group']
        self._gg = Entity._session.client("greengrass")

    def _do_create(self):
        log.debug("Preparing resources list...")
        res = []
        for r in self._group['Resources']:
            # Convert from a simplified form to AWS API input
            resource = dict(Name=r.pop('Name'), Id=r.pop('Id'))
            resource['ResourceDataContainer'] = r
            res.append(resource)

        log.debug("Resources list is ready:\n{0}".format(pretty(res)))

        log.info("Creating resource definition: '{0}'".format(self.name))
        res_def = rinse(self._gg.create_resource_definition(
            Name=self.name,
            InitialVersion={'Resources': res}
        ))

        self._state.update('Resources', res_def)

        res_def_ver = rinse(self._gg.get_resource_definition_version(
            ResourceDefinitionId=self._state.get('Resources.Id'),
            ResourceDefinitionVersionId=self._state.get('Resources.LatestVersion')
        ))

        self._state.update('Resources.LatestVersionDetails', res_def_ver)

    def _do_remove(self):
        log.debug("Deleting resources definition '{0}' Id='{1}".format(
            self.name, self._state.get('Resources.Id')))
        self._gg.delete_resource_definition(
            ResourceDefinitionId=self._state.get('Resources.Id'))

        self._state.remove(self.type)
