
set -x
# Copy certificates
sudo cp /vagrant/certs/* /greengrass/certs
sudo cp /vagrant/config/* /greengrass/config
sudo cp /vagrant/downloads/root.ca.pem /greengrass/certs

# A previous group definition is no good no more, restore original
sudo cp /greengrass/ggc/deployment/group/group.json /greengrass/ggc/deployment/group/group.bak
sudo cp /greengrass/ggc/deployment/group/group.json.orig /greengrass/ggc/deployment/group/group.json
set +x
# Remind to restart GGC daemon
echo "Restart GGC daemon to pick up the changes: greengrassd restart"
