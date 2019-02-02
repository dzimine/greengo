import unittest
import shutil
import os

from greengo import utils

# logging.basicConfig(
#     format='%(asctime)s|%(name).10s|%(levelname).5s: %(message)s',
#     level=logging.DEBUG)

TEST_KEY_PATH = "tests/certs"


class SaveKeysTest(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        try:
            shutil.rmtree(TEST_KEY_PATH)
        except OSError:
            pass

    def test_save_keys(self):
        keys = {
            "certificateArn": "arn:aws:iot:us-west-2:000000000000:cert/7f8b7783887d381c79e5f07db930523ded0bff037dd91b99db802383b1a78d88",
            "certificateId": "7f8b7783887d381c79e5f07db930523ded0bff037dd91b99db802383b1a78d88",
            "certificatePem": "-----BEGIN CERTIFICATE-----\nPEMxxxXXXXXXXXXXXXXXXXXXXXXX==\n-----END CERTIFICATE-----\n",
            "keyPair": {
                "PrivateKey": "-----BEGIN RSA PRIVATE KEY-----\nPRIVATEKEYxxxXXXXXXXXXXXXXXXXXXXXXX=\n-----END RSA PRIVATE KEY-----\n",
                "PublicKey": "-----BEGIN PUBLIC KEY-----\nPUBLICKEYxxxXXXXXXXXXXXXXXXXXXXXXX\n-----END PUBLIC KEY-----\n"
            }
        }

        utils.save_keys(TEST_KEY_PATH, 'Test', keys)

        self.assertTrue(
            os.path.isfile(os.path.join(TEST_KEY_PATH, 'Test.pem')), "PEM file not created")
        self.assertTrue(
            os.path.isfile(os.path.join(TEST_KEY_PATH, 'Test.pub')), "PUB file not created")
        self.assertTrue(
            os.path.isfile(os.path.join(TEST_KEY_PATH, 'Test.key')), "KEY file note cretaed")
