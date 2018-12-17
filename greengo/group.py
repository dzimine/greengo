from entity import Entity
import logging

log = logging.getLogger(__name__)


class Group(Entity):

    def __init__(self, group, state):
        super(Group, self).__init__(group, state)
        self.type = 'Group'
        self.name = group['Group']['name']

        self._gg = Entity._session.client("greengrass")
        # self._iot = s.client("iot")
        # self._lambda = s.client("lambda")
        # self._iam = s.client("iam")

    def _do_create(self, update_group_version):
        log.info("Creating group '{}'".format(self._group['Group']['name']))
        g = self._gg.create_group(Name=self.name)
        self._state.update(self.type, g)

    def _do_remove(self):
        log.info("Deleting group '{0}'".format(self._state.get('Group')['Id']))
        self._gg.delete_group(self._state.get('Group')['Id'])
