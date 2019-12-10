# LocalResource
This example is intended to demonstrate how to access local resources within the
greengo framework
1. On your core device, install the greengrass core runtime and any other
software needed for your device to function as a core.
2. In this directory, run `greengo --config_file lr.greengo.yaml create`.
This will create the group definition with requisite local resource access
policies
3. Transfer the contents of /certs and /config to the core device.
4. Start the greengrass daemon on the core device.
5. On your core device run
`sudo mkdir /src && sudo mkdir /dest`
and
`sudo mkdir /src/LRAtest && sudo mkdir /dest/LRAtest`
. Our lambda will be reading and writing to these directories, so run
`sudo chmod 0775 /src/LRAtest && sudo chmod 0775 /src/LRAtest` to give the
correct user group the correct permissions
6. On your local machine run `greengo --config_file lr.greengo.yaml deploy`
7. Subscribe to LRA/test on the test menu in the AWS IoT console. Publish the
default json message to the topic invoke/LRAFunction. You should see output from
the lambda as soon as the message is published
