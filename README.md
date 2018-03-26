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
git clone https://github.com/dzimine/greenfly
cd greenfly
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
Yeah this sucks... I'll automate it later, meantime PR welcome.


## Play

1. Create GreenGrass Group definition in AWS

    Fancy yourself with the group definitions in `group.yaml`, and run `greenfly`:

    ```
    python greenfly.py create
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
    python greenfly.py deploy
    ```

4. Clean-up when done playing.

    Remove the group definitions on AWS:

    ```
    python greenfly.py remove
    ```

    Ditch the Vagrant VM:

    ```
    vagrant destroy
    ```

> NOTE: If you create a new group but keep the GreenGrass Core in Vagrant VM,
> you must update it with newly generated certificates and `config.json` file
> before deploying the group.
> Run `/vagrant/scripts/update_ggc.sh` from the Vagrant VM.

# Details

Coming... Stay tuned.

# When something goes wrong
Yes, it's not *if* but *when* somethings throws out, leaving the setup in half-deployed,
and you gotta pick up the pieces. Remember:

* You are still not worse off doing this manually: you at least have all the `ARN`
and `Id` of all resources to clean-up.
* DON'T DELETE `.group_state.json` file: it contains references to everything you need to delete.
* Do what it takes to roll forward - if you're close to successful deployment, or roll-back - to clean things up and start from scratch.
* Pay forward: add a patch to whatever broke to proof it from happening again.

