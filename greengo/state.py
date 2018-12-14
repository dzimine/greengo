class State(object):

    def __init__(self):
        # Entities map: { entityName: entity }
        self._entities = {}

    # load from file, save to file
    def load(self):
        pass

    def save(self):
        pass

    def exists(self):
        return False

    def checkpoint(self, entity):
        # 1. update entity in a map (I'll need entity name... )
        # 2. save in file
        pass
