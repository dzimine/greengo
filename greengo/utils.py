import os
import errno
import yaml
import logging

log = logging.getLogger(__name__)


def mkdir(path):
    ''' Create directory with entier path, like `mkdir -p`. '''
    try:
        os.makedirs(path)
    except OSError as exc:
        if not (exc.errno == errno.EEXIST and os.path.isdir(path)):
            raise


def rinse(boto_response):
    ''' Remove ResponseMetadata block from Boto / AWS API respone. '''
    boto_response.pop('ResponseMetadata', None)
    return boto_response


def pretty(d):
    """ Pretty object as YAML. """
    return yaml.safe_dump(d, default_flow_style=False)


def save_keys(path, name, keys_cert):
    try:
        path = path + '/' if not path.endswith('/') else path
        mkdir(path)
        certname = path + name + ".pem"
        public_key_file = path + name + ".pub"
        private_key_file = path + name + ".key"
        with open(certname, "w") as pem_file:
            pem = keys_cert['certificatePem']
            pem_file.write(pem)
            log.info("Thing Name: {0}; PEM certifiate file: {1}".format(name, certname))

        with open(public_key_file, "w") as pub_file:
            pub = keys_cert['keyPair']['PublicKey']
            pub_file.write(pub)
            log.info("Thing Name: {0}; Public Key File: {1}".format(name, public_key_file))

        with open(private_key_file, "w") as prv_file:
            prv = keys_cert['keyPair']['PrivateKey']
            prv_file.write(prv)
            log.info("Thing Name: {0}; Private Key File: {1}".format(name, private_key_file))

    except OSError as e:
        log.error('Error while writing an certificate files. {0}'.format(e))
    except KeyError as e:
        log.error('Error while writing an certificate files. {0}'
                  'Check the keys {1}'.format(e, keys_cert))
