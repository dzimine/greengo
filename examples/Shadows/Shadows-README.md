# Shadows
## For experimenting with device shadows
This example will automatically set up most of the code required for module 5 of the [AWS Greengrass tutorials](https://docs.aws.amazon.com/greengrass/latest/developerguide/module5.html).
As usual, you are still responsible for transferring device certificates with your method of choice. Additionally, on your non-core devices you must install the AWS IoT python sdk.
This is described in detail in module 5. Note also you will have to change all instances of
`GG_Switch` and `GG_TrafficLight` to `GG_Switch2` and `GG_TrafficLight2` in module 5 for the yaml configuration to work.
To get started, run
```
python ..\greengo\greengo.py --config_file .\shadow2.greengo.yaml create
```
Once you have transferred the appropriate certificates (in ./certs) to the devices and core, and transferred the config file (in ./config) to the core, run
```
python ..\greengo\greengo.py --config_file .\shadow2.greengo.yaml deploy
```
Then follow the tutorial for running the device python scripts, and updating shadow status in the cloud.
