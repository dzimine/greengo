import os
import sys
import platform
from threading import Timer

sys.path.append(os.path.dirname(os.path.realpath(__file__)))

import greengrasssdk

INTERVAL = 5

# Creating a greengrass core sdk client
client = greengrasssdk.client('iot-data')

# Retrieving platform information to send from Greengrass Core
my_platform = platform.platform()


def run():
    print "Executing run..."
    if not my_platform:
        client.publish(topic='hello/world', payload='Hello from Greengrass Core.')
    else:
        client.publish(
            topic='hello/world',
            payload='Hello from Greengrass Core running on platform: {}'.format(my_platform))

    # Asynchronously schedule this function to be run again in 5 seconds
    Timer(INTERVAL, run).start()

# Start executing the function above
run()


# This is a dummy handler and will not be invoked
# Instead the code above will be executed in an infinite loop for our example
def handler(event=None, context=None):
    return
