import os
import json
import unittest
import pytest
from mock import patch, MagicMock

from greengo import greengo


class SessionFixture():
    region_name = 'moon-darkside'

    def __init__(self):
        self.mock = MagicMock()
        self.mock.describe_endpoint = MagicMock(
            return_value={'endpointAddress': "xxx.iot.moon-darkside.amazonaws.com"})

    def client(self, name):
        return self.mock


class CommandTest(unittest.TestCase):
    def setUp(self):
        with patch.object(greengo.session, 'Session', SessionFixture):
            self.gg = greengo.Commands()

    def tearDown(self):
        try:
            os.remove(greengo.STATE_FILE)
        except OSError:
            pass

    def test_create___all_new(self):
        self.gg.create()

    def test_remove(self):
        self.gg.remove()

    def test_create_subscriptions(self):
        self.gg.create_subscriptions()

    def test_remove_subscriptions(self):
        self.gg.remove_subscriptions()

