from entity import Entity
import logging

from utils import pretty, rinse

log = logging.getLogger(__name__)


class Subscriptions(Entity):

    def __init__(self, group, state):
        super(Subscriptions, self).__init__(group, state)
        self.type = 'Subscriptions'
        self.name = group['Group']['name'] + '_subscriptions'

        self._requirements = ['Group']
        self._gg = Entity._session.client("greengrass")

    def _do_create(self):
        log.debug("Preparing subscription list...")
        subs = []
        for i, s in enumerate(self._group['Subscriptions']):
            log.debug("Subscription '{0}' - '{1}': {2}->{3}'".format(
                i, s['Subject'], s['Source'], s['Target']))
            subs.append({
                'Id': str(i),
                'Source': self._resolve_subscription_destination(s['Source']),
                'Target': self._resolve_subscription_destination(s['Target']),
                'Subject': s['Subject']
            })
        log.debug("Subscription list is ready:\n{0}".format(pretty(subs)))

        log.info("Creating subscription definition: '{0}'".format(self.name))
        sub_def = rinse(self._gg.create_subscription_definition(
            Name=self.name,
            InitialVersion={'Subscriptions': subs}
        ))

        self._state.update('Subscriptions', sub_def)

        sub_def_ver = rinse(self._gg.get_subscription_definition_version(
            SubscriptionDefinitionId=self._state.get('Subscriptions.Id'),
            SubscriptionDefinitionVersionId=self._state.get('Subscriptions.LatestVersion')
        ))
        self._state.update('Subscriptions.LatestVersionDetails', sub_def_ver)

    def _do_remove(self):
        log.debug("Deleting subscription definition '{0}' Id='{1}".format(
            self.name, self._state.get('Subscriptions.Id')))
        self._gg.delete_subscription_definition(
            SubscriptionDefinitionId=self._state.get('Subscriptions.Id'))

    def _resolve_subscription_destination(self, d):
        p = [x.strip() for x in d.split('::')]
        if p[0] == 'cloud':
            return p[0]
        elif p[0] == 'Lambda':
            return self._lookup_lambda_qualified_arn(p[1])
        elif p[0] == 'Device':
            return self._lookup_device_arn(p[1])
        elif p[0] == 'GGShadowService':
            return p[0]
        elif p[0] == 'Connector':
            return self._lookup_connector_arn(p[1])
        else:
            raise ValueError(
                "Error parsing subscription destination '{0}'. Allowed values: "
                "'Lambda::', 'Device::', 'Connector::', 'GGShadowService', or 'cloud'.".format(d))

    def _lookup_lambda_qualified_arn(self, name):
        for l in self._state.get('FunctionDefinition.LatestVersionDetails.Definition.Functions', []):
            if l['Id'] == name:
                return l['FunctionArn']
        log.error("Lambda '{0}' not found".format(name))
        return None

    def _lookup_device_arn(self, name):
        raise NotImplementedError("WIP: Devices not implemented yet.")

    def _lookup_connector_arn(self, name):
        for l in self._state.get('Connectors.LatestVersionDetails.Definition.Connectors'):
            if l['Id'] == name:
                return l['ConnectorArn']
        log.error("Connector '{0}' not found".format(name))
        return None
