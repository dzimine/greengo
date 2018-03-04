# -*- mode: ruby -*-
# vi: set ft=ruby :

hostname   = ENV['HOSTNAME'] ? ENV['HOSTNAME'] : 'greengrass'
box        = ENV['BOX'] ? ENV['BOX'] : 'ubuntu/xenial64'

# Vagrantfile API/syntax version. Don't touch unless you know what you're doing!
VAGRANTFILE_API_VERSION = "2"

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|
  config.vm.define "greengrass" do |gg|
    # Box details
    gg.vm.box = "#{box}"
    gg.vm.hostname = "#{hostname}"

    # Box Specifications
    gg.vm.provider :virtualbox do |vb|
      vb.name = "#{hostname}"
      vb.memory = 2048
      vb.cpus = 2
    end

    # NFS-synced directory for pack development
    # Change "/path/to/directory/on/host" to point to existing directory on your laptop/host and uncomment:
    # config.vm.synced_folder "/path/to/directory/on/host", "/opt/stackstorm/packs", :nfs => true, :mount_options => ['nfsvers=3']

    # Configure a private network
    gg.vm.network :private_network, ip: "192.168.16.30"

    # Public (bridged) network may come handy for external access to VM (e.g. sensor development)
    # See https://www.vagrantup.com/docs/networking/public_network.html
    # gg.vm.network "public_network", bridge: 'en0: Wi-Fi (AirPort)'

    gg.vm.provision "shell" do |s|
      s.path = "scripts/install.sh"
      s.privileged = false
    end
  end

end
