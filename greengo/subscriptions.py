from entity import Entity
import logging

log = logging.getLogger(__name__)


class Subscriptions(Entity):

    def __init__(self, group, state):
        super(Subscriptions, self).__init__(group, state)
        self.name = 'Subscriptions'

    def _do_create(self, update_group_version=True):
        log.info("Creating subscription '{}'".format(self._group['Subscriptions']))
        self._state.update(self.name, {})

    def _do_remove(self):
        pass
