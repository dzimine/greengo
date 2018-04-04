# Boilerplate for AWS IoT Greengrass

A starter project to bring up (and clean-up!) AWS Greengrass setup for play and profit. If you followed the [GreenGrass Getting Started Guide](https://docs.aws.amazon.com/greengrass/latest/developerguide/gg-gs.html), here you find it automated, as code.

> Work In Progress !

Describe your Greengrass group in `group.yaml`, write Lambda functions and device clients, provision Greengrass Core in Vagrant VM, deploy, and clean up.

Inspired by [aws-iot-elf (Extremely Low Friction)](https://github.com/awslabs/aws-iot-elf) and [aws-greengrass-group-setup](https://github.com/awslabs/aws-greengrass-group-setup).

## Pre-requisits

* A computer with Linux/MacOS, Python, git (dah!)
* [Vagrant](https://www.vagrantup.com/docs/installation/) with [VirtualBox](https://www.virtualbox.org/wiki/Downloads)
* AWS CLI [installed](http://docs.aws.amazon.com/cli/latest/userguide/installing.html) and [configured](http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html). Consider using [named profiles](https://docs.aws.amazon.com/cli/latest/userguide/cli-multiple-profiles.html).


## Set it Up

Clone the repo:

```
git clone https://github.com/dzimine/greengo
cd greengo
```

Create and activate a virtual environment, install the dependencies

```
virtualenv venv
source ~/dev/aws-iot-elf/venv/bin/activate
pip install -r requirements.txt
```

Manually [*] download GreenGrassCore binary and place it in the `./downloads` directory.
Sign in to the AWS Management Console, navigate to the AWS IoT console,
and download the AWS Greengrass
Core Software from [Software section](https://us-west-2.console.aws.amazon.com/iotv2/home?region=us-west-2#/
software/greengrass).
Yeah this sucks... I will automate it later. In the meantime, PR is most welcome!


## Play

1. Create GreenGrass Group definition in AWS

    Fancy yourself with the group definitions in `group.yaml`, and run `greengo`:

    ```
    python greengo.py create
    ```
    When runs with no errors, it creates all greengrass group artefacts on AWS
    and places certificates and `config.json` for GreenGrass Core in `./certs`
    and `./config` for Vagrant to use in provisioning on next step.
    

2. Provision VM with GreenGrass Core with Vagrant

    ```
    vagrant up
    ```

3. Deploy Greengrass Group to the Core on the VM. 

    ```
    python greengo.py deploy
    ```
4. Check that everything works - see the ["Check" section](#check-the-deployment)  below.

5. **Profit !**

6. Clean-up when done playing.

    Remove the group definitions on AWS:

    ```
    python greengo.py remove
    ```

    Ditch the Vagrant VM:

    ```
    vagrant destroy
    ```

> NOTE: If you want to create a new group but keep the Greengrass Core in the same Vagrant VM,
> you must update it with newly generated certificates and `config.json` file
> before deploying the group, and also reset deployment by getting
> the `deployments/group/group.json` back to virgin.
> 
> To do it: login to the Greengrass Vagrant VM and run `/vagrant/scripts/update_ggc.sh` on the Vagrant VM.

# Details

## Check the deployment
How to be sure ~~everything~~ something works? Follow this:

1. Create greengrass group in AWS IoT: `greengo create`.
2. Prepare GGC on the VM: update certificates, reset `group.json`, restart the `greengrassd`. 
3. Deploy with `greengo deploy`. Check:
    * Check the deployment status, should be 'Success'
4. Explore Greengrass Core on your vagrant VM.
    * Login to Vagrant VM. You should nkow Vagrant but for the off case: `vagrant ssh`.
    * Check the GGC logs `runtime.log` and `python_runtime.log` under `/greengrass/ggc/var/log/system`. Runtime log should have a line about starting your lambda, or an error why the funtion is not started. In many cases (like not enough memory for Lambda), the deployment is 'Success' but the function fails to start. The errors can only be seen in the `runtime.log`. 
      If the function starts successfully, `runtime.log` will contain a message like 
    ```
    [2018-03-31T08:48:40.57Z][INFO]-Starting worker arn:aws:lambda:us-west-2:0000000000:function:GreengrassHelloWorld:12
    ```
    * Find and check your own Lambda log under `/greengrass/ggc/var/log/system`.
    * Check the greengrassd process: `ps aux | grep greengrassd`. 
      Depending on deployment you might have several processes.       
5. In AWS console, check the MQTT topic with IoT MQTT Test page:
    ```
    REGION=`aws configure get region`; open https://$REGION.console.aws.amazon.com/iot/home?region=$REGION#/test
    ```
    Subscribe to the topic (e.g., `hello/world`), see the messages sent by the Greengrass Lambda function.


# When something goes wrong
At this time `greengo` is just a prototype, a work-in-progress. Therefore it's not *if* but *when* somethings throws out, leaving the setup in half-deployed,
and you gotta pick up the pieces. Remember:

* You are still not worse off doing this manually: you at least have all the `ARN`
and `Id` of all resources to clean-up.
* DON'T DELETE `.gg/gg_state.json` file: it contains references to everything you need to delete. Copy it somewhere and use the `Id` and `Arn` of created resources to clean up the pieces. 
* Do what it takes to roll forward - if you're close to successful deployment, or roll-back - to clean things up and start from scratch.

Please pay forward: fadd a patch to whatever broke to proof it from happening again.

