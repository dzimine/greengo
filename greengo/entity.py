import logging

from .utils import pretty

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

    def add_dependant(self, entity):
        self._dependants.add(entity)

    def create(self, update_group_version=True):
        if self._pre_create():
            self._do_create()
            self._post_create(update_group_version)

    def _pre_create(self):
        log.info("Creating {}...".format(self.type.lower()))

        if not self._group.get(self.type):
            log.warning("{} not defined, skipping.".format(self.type))
            return False

        if self._state.get(self.type):
            log.warning("{} already created. Remove before creating again.".format(self.type))
            return False

        # Check if requred objects alrady created, if not - warn and exit.
        missed = [r for r in self._requirements if r not in self._state.entities()]
        if missed:
            log.warning("{} must be created before {}. Please create first.".format(
                ', '.join(missed), self.type))
            return False

        return True

    def _do_create(self):
        raise NotImplementedError

    def _post_create(self, update_group_version):
        if update_group_version:
            log.info("Updating group version with new {}...".format(self.type))
            self.create_group_version(self._state)

        log.info("{} created OK!".format(self.type))

    def remove(self, update_group_version=True):
        if self._pre_remove():
            self._do_remove()
            self._post_remove(update_group_version)

    def _pre_remove(self):
        log.info("Removing {}".format(self.type.lower()))

        if not self._state.get(self.type):
            log.warning("{} does not exist, skipping remove.".format(self.type))
            return False

        return True

    def _do_remove(self):
        raise NotImplementedError

    def _post_remove(self, update_group_version):
        if update_group_version:
            log.info("Updating group version with {} removed...".format(self.type))
            self.create_group_version(self._state)

        self._state.remove(self.type)
        log.info("{} removed OK!".format(self.type.lower()))

    @classmethod
    def create_group_version(klass, state):
        if not state.get('Group.Id'):
            log.debug("Attempting to update group version but the group doesn't exist, skipping!")
            return

        # Compile a list of non-empty arguments from the super-set,
        # https://docs.aws.amazon.com/greengrass/latest/apireference/definitions-groupversion.html
        kwargs = dict(
            GroupId=state.get('Group')['Id'],  # REQUIRED
            CoreDefinitionVersionArn=state.get(
                'CoreDefinition.LatestVersionArn', ""),
            FunctionDefinitionVersionArn=state.get(
                'Lambdas.FunctionDefinition.LatestVersionArn', ""),
            SubscriptionDefinitionVersionArn=state.get(
                'Subscriptions.LatestVersionArn', ""),
            LoggerDefinitionVersionArn=state.get(
                'Loggers.LatestVersionArn', ""),
            ResourceDefinitionVersionArn=state.get(
                'Resources.LatestVersionArn', ""),
            ConnectorDefinitionVersionArn=state.get(
                'Connectors.LatestVersionArn', ""),
            DeviceDefinitionVersionArn=""  # NOT IMPLEMENTED
        )
        args = dict((k, v) for k, v in kwargs.items() if v)
        log.debug("Creating group version with settings:\n{0}".format(pretty(args)))

        _gg = Entity._session.client("greengrass")
        group_ver = _gg.create_group_version(**args)

        state.update('Group.Version', group_ver)
