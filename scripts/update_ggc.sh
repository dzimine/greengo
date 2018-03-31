echo "Reseting Greengrass Core for a new group."

echo "Copy certificates..."
sudo cp /vagrant/certs/* /greengrass/certs
sudo cp /vagrant/config/* /greengrass/config
sudo cp /vagrant/downloads/root.ca.pem /greengrass/certs


echo "A previous group definition is no good no more, restore original..."
sudo cp /greengrass/ggc/deployment/group/group.json /greengrass/ggc/deployment/group/group.bak
sudo cp /greengrass/ggc/deployment/group/group.json.orig /greengrass/ggc/deployment/group/group.json

echo "Ditch Lambda leftovers from previous deployments..."
sudo rm -rf  /greengrass/ggc/deployment/lambda/*


echo "Restart GGC daemon to pick up the changes..."
/greengrass/ggc/core/greengrassd restart
