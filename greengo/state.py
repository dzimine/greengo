import os
import errno
import logging
import json

from . import utils

log = logging.getLogger(__name__)


class State(object):

    def __init__(self, file):
        # Entities map: { entityName: entity }
        self._entities = {}
        self._state = {}
        self._file = file
        if file:
            self.load()

    def load(self):
        if not os.path.exists(self._file):
            log.debug("Group state file {0} not found, assume new group.".format(self._file))
        else:
            log.debug("Loading group state from {0}".format(self._file))
            with open(self._file, 'r') as f:
                self._state = json.load(f)

    def save(self):
        if not self._file:
            return
        try:
            with open(self._file, 'w') as f:
                json.dump(self._state, f, indent=2,
                          separators=(',', ': '), sort_keys=True, default=str)
                # log.debug("Updated group state in state file '{0}'".format(self._file))
        except IOError as e:
            # Assume we miss the directory... Create it and try again
            if e.errno != errno.ENOENT:
                raise e
            utils.mkdir(os.path.dirname(self._file))
            self.save()

    def __str__(self):
        if not self._state:
            return "State not created."
        return utils.pretty(self._state)

    def exists(self):
        return bool(self._state)

    def update(self, key, body):
        '''
        Updates nested keys using dot as separator, like 'foo.bar.buz'.
        Creates missing keys as nessessary.
        '''
        tree = self._state
        prev = None
        for k in key.split('.'):
            if prev is not None:
                tree = tree.setdefault(prev, {})
            prev = k

        tree[prev] = body
        self.save()

    def entities(self):
        ''' Get list of entities - top level keys '''
        return self._state.keys()

    def get(self, key=None, default=None):
        '''
        Get value. Key may be nested using dot as separator, like 'foo.bar.buz'.
        '''
        branch = self._state
        if key:
            for k in key.split('.'):
                branch = branch.get(k, default)
                if branch == default:
                    break

        return branch

    def remove(self, key=None):
        if key:
            try:
                (path, dot, k) = key.rpartition('.')
                if path:
                    branch = self.get(path)
                    if not branch or type(branch) is not dict:
                        raise KeyError
                    branch.pop(k)
                else:
                    self._state.pop(key)
                self.save()
            except KeyError:
                log.warning("Can not remove key '{}' from State - missing".format(key))
        else:
            self._state = {}
            if self._file:
                try:
                    os.remove(self._file)
                except OSError:
                    log.warning("State file not removed (missing?): {}".format(self._file))
