# Demonstrates a simple use case of local resource access.
# This Lambda function writes a file "test" to a volume mounted inside
# the Lambda environment under "/dest/LRAtest". Then it reads the file and
# publishes the content to the AWS IoT "LRA/test" topic.
#
# Eventually we will change this "try" to something that checks for connectivity with the cloud

import sys
import greengrasssdk
import platform
import os
import logging

# Create a Greengrass Core SDK client.
client = greengrasssdk.client('iot-data')
volumePath = '/dest/LRAtest'

def function_handler(event, context):
    client.publish(topic='LRA/test', payload='Sent from AWS IoT Greengrass Core.')
    try:
        volumeInfo = os.stat(volumePath)
        client.publish(topic='LRA/test', payload=str(volumeInfo))
        with open(volumePath + '/test', 'a') as output:
            output.write('Successfully write to a file.\n')
        with open(volumePath + '/test', 'r') as myfile:
            data = myfile.read()
        client.publish(topic='LRA/test', payload=data)
    except Exception as e:
        logging.error("Experiencing error :{}".format(e))
    return
