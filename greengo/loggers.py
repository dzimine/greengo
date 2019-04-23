import logging

from .utils import rinse
from .entity import Entity

log = logging.getLogger(__name__)


class Loggers(Entity):

    def __init__(self, group, state):
        super(Loggers, self).__init__(group, state)
        self.type = 'Loggers'
        self.name = group['Group']['name'] + '_loggers'

        self._requirements = ['Group']
        self._gg = Entity._session.client("greengrass")

    def _do_create(self):
        log.info("Creating loggers definition: '{0}'".format(self.name))

        l_def = rinse(self._gg.create_logger_definition(
            Name=self.name,
            InitialVersion={'Loggers': self._group['Loggers']}
        ))

        self._state.update('Loggers', l_def)

        l_def_ver = rinse(self._gg.get_logger_definition_version(
            LoggerDefinitionId=self._state.get('Loggers.Id'),
            LoggerDefinitionVersionId=self._state.get('Loggers.LatestVersion')
        ))

        self._state.update('Loggers.LatestVersionDetails', l_def_ver)

    def _do_remove(self):
        log.debug("Deleting logger definition '{0}' Id='{1}".format(
            self.name, self._state.get('Loggers.Id')))

        self._gg.delete_logger_definition(
            LoggerDefinitionId=self._state.get('Loggers.Id'))

        self._state.remove(self.type)
