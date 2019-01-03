import logging

from utils import pretty

log = logging.getLogger(__name__)


# Alternative names: Definition
class Entity(object):
    ''' The base class for Greengrass model elements '''

    _session = None

    def __init__(self, group, state):
        self.type = "REPLACE WITH CHILD CLASS TYPE!"
        self._state = state
        self._group = group

        # Objects dependent on this, (immediate children),
        # thus must be removed prior to `this` object is removed.
        self._dependants = set()

        # Object types that must be created prior to this object's creation
        # Note that it's list of Types (classes), not instances.
        self._requirements = []

    def _pre_create(self, update_group_version=True):
        log.info("Creating {}...".format(self.type.lower()))
        # check if requred objects alrady created, if not, warn and exit.
        # do the work of your own creation
        # update requirements
        for r in self._requirements:
            r.add_dependant(self)
        # add yourself to State
        # Write to file
        pass

    def _do_create(self, update_group_version):
        raise NotImplementedError

    def _post_create(self):
        log.info("{} created OK!".format(self.type))

    def create(self, update_group_version=True):
        self._pre_create()
        self._do_create(update_group_version)
        self._post_create()

    def _pre_remove(self):
        log.info("Removing {}".format(self.type.lower()))

    def _do_remove(self):
        raise NotImplementedError

    def _post_remove(self):
        log.info("{} removed OK!".format(self.type.lower()))

    def remove(self):
        self._pre_remove()
        self._do_remove()
        self._post_remove

    def add_dependant(self, entity):
        self._dependants.add(entity)

    @classmethod
    def create_group_version(klass, state):
        # Compile a list of non-empty arguments from the super-set,
        # https://docs.aws.amazon.com/greengrass/latest/apireference/definitions-groupversion.html
        kwargs = dict(
            GroupId=state.get('Group')['Id'],  # REQUIRED
            CoreDefinitionVersionArn=state.get(
                'CoreDefinition', {}).get('LatestVersionArn', ""),
            FunctionDefinitionVersionArn=state.get(
                'FunctionDefinition', {}).get('LatestVersionArn', ""),
            SubscriptionDefinitionVersionArn=state.get(
                'Subscriptions', {}).get('LatestVersionArn', ""),
            LoggerDefinitionVersionArn=state.get(
                'Loggers', {}).get('LatestVersionArn', ""),
            ResourceDefinitionVersionArn=state.get(
                'Resources', {}).get('LatestVersionArn', ""),
            ConnectorDefinitionVersionArn=state.get(
                'Connectors', {}).get('LatestVersionArn', ""),
            DeviceDefinitionVersionArn=""  # NOT IMPLEMENTED
        )
        args = dict((k, v) for k, v in kwargs.items() if v)
        log.debug("Creating group version with settings:\n{0}".format(pretty(args)))

        _gg = Entity._session.client("greengrass")
        group_ver = _gg.create_group_version(**args)

        # TODO:XXX refactor state and save nested keys.
        state.update('Group.Version', group_ver)
