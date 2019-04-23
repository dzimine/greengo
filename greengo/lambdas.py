import shutil
import os
from time import sleep
import json
from botocore.exceptions import ClientError
import logging

from .entity import Entity
from .utils import pretty, rinse

MAGIC_DIR = '.gg'  # XXX: better way?

log = logging.getLogger(__name__)


class Lambdas(Entity):
    def __init__(self, group, state):
        super(Lambdas, self).__init__(group, state)
        self.type = 'Lambdas'
        self.name = group['Group']['name'] + '_lambdas'
        self._LAMBDA_ROLE_NAME = "{0}_Lambda_Role".format(self.name)

        self._requirements = ['Group']
        self._gg = Entity._session.client("greengrass")
        self._iam = Entity._session.client("iam")
        self._lambda = Entity._session.client("lambda")

    def _do_create(self):
        functions = []
        self._state.update('Lambdas', {})
        self._state.update('Lambdas.Functions', [])  # XXX do this better.
        for l in self._group['Lambdas']:
            log.info("Creating Lambda function '{0}'".format(l['name']))

            # Use existing role if provided, or create & use default role.
            role_arn = l['role'] if 'role' in l else self._default_lambda_role_arn()
            log.info("Assuming role '{0}'".format(role_arn))

            zf = shutil.make_archive(
                os.path.join(MAGIC_DIR, l['name']), 'zip', l['package'])
            log.debug("Lambda deployment Zipped to '{0}'".format(zf))

            for retry in range(3):
                try:
                    with open(zf, 'rb') as f:
                        lr = self._lambda.create_function(
                            FunctionName=l['name'],
                            Runtime=l['runtime'],
                            Role=role_arn,
                            Handler=l['handler'],
                            Code=dict(ZipFile=f.read()),
                            Environment=dict(Variables=l.get('environment', {})),
                            Publish=True
                        )
                        # Break from retry cycle if lambda is created
                        break
                except ClientError as e:  # Catch the right exception
                    if "The role defined for the function cannot be assumed by Lambda" in str(e):
                        # Function creation immediately after role creation fails with
                        # "The role defined for the function cannot be assumed by Lambda."
                        # See StackOverflow https://goo.gl/eTfqsS
                        log.warning("We hit AWS bug: the role is not yet propagated. "
                                    "Taking 5 sec nap")
                        sleep(5)
                        continue
                    else:
                        raise(e)

            lr['ZipPath'] = zf

            self._state.get('Lambdas.Functions').append(rinse(lr))
            self._state.save()  # This is needed as `append` only modified state in memory.
            log.info("Lambda function '{0}' created".format(lr['FunctionName']))

            # Auto-created alias uses the version of just published function
            alias = self._lambda.create_alias(
                FunctionName=lr['FunctionName'],
                Name=l.get('alias', 'default'),
                FunctionVersion=lr['Version'],
                Description='Created by greengo'
            )
            log.info("Lambda alias created. FunctionVersion:'{0}', Arn:'{1}'".format(
                alias['FunctionVersion'], alias['AliasArn']))

            functions.append({
                'Id': l['name'],
                'FunctionArn': alias['AliasArn'],
                'FunctionConfiguration': l['greengrassConfig']
            })

        log.debug("Function definition list ready:\n{0}".format(pretty(functions)))

        log.info("Creating function definition: '{0}'".format(self.name + '_func_def_1'))
        fd = self._gg.create_function_definition(
            Name=self.name + '_func_def_1',
            InitialVersion={'Functions': functions}
        )
        self._state.update('Lambdas.FunctionDefinition', rinse(fd))

        fd_ver = self._gg.get_function_definition_version(
            FunctionDefinitionId=self._state.get('Lambdas.FunctionDefinition.Id'),
            FunctionDefinitionVersionId=self._state.get('Lambdas.FunctionDefinition.LatestVersion'))

        self._state.update('Lambdas.FunctionDefinition.LatestVersionDetails', rinse(fd_ver))

    def _do_remove(self):

        if not self._state.get('Lambdas.FunctionDefinition'):
            log.warning("Function definition was not created. Moving on...")
        else:
            fd_name = self._state.get('Lambdas.FunctionDefinition.Name')
            fd_id = self._state.get('Lambdas.FunctionDefinition.Id')
            log.info("Deleting function definition '{0}' Id='{1}".format(fd_name, fd_id))
            self._gg.delete_function_definition(FunctionDefinitionId=fd_id)
            self._state.remove('Lambdas.FunctionDefinition')

        if not self._state.get('Lambdas.LambdaRole'):
            log.warning("Lambda Role was not created. Moving on...")
        else:
            log.info("Deleting default lambda role '{0}'".format(self._LAMBDA_ROLE_NAME))
            self._remove_default_lambda_role()
            self._state.remove('Lambdas.LambdaRole')

        if not self._state.get('Lambdas.Functions'):
            log.warning("Lambda Functions were not created. Moving on...")
        else:
            for l in self._state.get('Lambdas.Functions'):
                log.info("Deleting Lambda function '{0}'".format(l['FunctionName']))
                self._lambda.delete_function(FunctionName=l['FunctionName'])
                try:
                    os.remove(l['ZipPath'])
                except OSError as e:
                    log.warning("Failed to remove local Lambda zip package: {}".format(e))

            self._state.remove('Lambdas.Functions')

    def update_lambda(self, lambda_name):
        functions = self._state.get('Lambdas.Functions')
        if not functions:
            log.info("No lambda functions created. Create first...")
            return

        lr = next((lr for lr in functions if lr['FunctionName'] == lambda_name), None)
        if not lr:
            log.error("No lambda function '{0}' found.".format(lambda_name))
            return

        l = next((l for l in self._group['Lambdas'] if l['name'] == lambda_name), None)
        if not l:
            log.error("No definition for lambda function '{0}'.".format(lambda_name))
            return

        log.info("Updating lambda function code for '{0}'".format(lr['FunctionName']))

        zf = shutil.make_archive(
            os.path.join(MAGIC_DIR, l['name']), 'zip', l['package'])
        log.debug("Lambda deployment Zipped to '{0}'".format(zf))

        with open(zf, 'rb') as fd:
            lr_updated = self._lambda.update_function_code(
                FunctionName=l['name'],
                ZipFile=fd.read(),
                Publish=True
            )

        fnew = [rinse(lr_updated) if f['FunctionName'] == lambda_name else f for f in functions]
        self._state.update('Lambdas.Functions', fnew)

        log.info("Lambda function '{0}' updated".format(lr['FunctionName']))

        log.info("Updating alias '{0}'...".format(l.get('alias', 'default')))
        alias = self._lambda.update_alias(
            FunctionName=lr['FunctionName'],
            Name=l.get('alias', 'default'),
            FunctionVersion=lr['Version']
        )

        log.info("Lambda alias updated. FunctionVersion:'{0}', Arn:'{1}'".format(
            alias['FunctionVersion'], alias['AliasArn']))
        # TODO: save alias? If so, where in state?
        # If the alias name changed in group,
        # then LambdaDefinitions should also be updated.

        log.info("Lambdas function {0} updated OK!".format(lambda_name))

    def _default_lambda_role_arn(self):
        # TODO(XXX): Refactor, merge with _create_default_lambda_role;
        #            consider not messing with state here, move it up.
        if self._state.get('Lambdas.LambdaRole'):
            log.info("Default lambda role '{0}' already creted, RoleId={1} ".format(
                self._LAMBDA_ROLE_NAME, self._state.get('LambdaRole.Role.RoleId')))
        else:
            try:
                role = self._create_default_lambda_role()
            except ClientError as e:
                if e.response['Error']['Code'] == 'EntityAlreadyExists':
                    role = self._iam.get_role(RoleName=self._LAMBDA_ROLE_NAME)
                    log.warning("Role {0} already exists, reusing.".format(self._LAMBDA_ROLE_NAME))
                else:
                    raise e

            self._state.update('Lambdas.LambdaRole', rinse(role))
        return self._state.get('Lambdas.LambdaRole.Role.Arn')

    def _create_default_lambda_role(self):
        # TODO: redo as template and read from definition .yaml
        log.info("Creating default lambda role '{0}'".format(self._LAMBDA_ROLE_NAME))
        role_policy_document = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "lambda.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"

                }
            ]
        }

        role = self._iam.create_role(
            RoleName=self._LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(role_policy_document)
        )

        log.info("Creating lambda role policy '{0}'".format(
            self._LAMBDA_ROLE_NAME + "_Policy"))
        inline_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents"
                    ],
                    "Resource": "arn:aws:logs:*:*:*"
                }
            ]
        }

        self._iam.put_role_policy(
            RoleName=self._LAMBDA_ROLE_NAME,
            PolicyName=self._LAMBDA_ROLE_NAME + "_Policy",
            PolicyDocument=json.dumps(inline_policy))

        return role

    def _remove_default_lambda_role(self):
        for p in self._iam.list_role_policies(RoleName=self._LAMBDA_ROLE_NAME)['PolicyNames']:
            log.info("Deleting lambda role policy '{0}'".format(p))
            self._iam.delete_role_policy(RoleName=self._LAMBDA_ROLE_NAME, PolicyName=p)

        log.info("Deleting default lambda role '{0}'".format(self._LAMBDA_ROLE_NAME))
        self._iam.delete_role(RoleName=self._LAMBDA_ROLE_NAME)
