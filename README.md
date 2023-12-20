# tljh-repo2docker

![Github Actions Status](https://github.com/plasmabio/tljh-repo2docker/workflows/Tests/badge.svg)

TLJH plugin to build and use Docker images as user environments. The Docker images are built using [`repo2docker`](https://repo2docker.readthedocs.io/en/latest/).

## Installation

During the [TLJH installation process](http://tljh.jupyter.org/en/latest/install/index.html), use the following post-installation script:

```bash
#!/bin/bash

# install Docker
sudo apt update
sudo apt install ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg

NODE_MAJOR=20
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list

sudo apt update
sudo apt install -y nodejs libfuse-dev python3-dev libcurl4-openssl-dev libssl-dev

# pull the repo2docker image
sudo docker pull gcr.io/nii-ap-ops/repo2docker:20220330
sudo docker pull gcr.io/nii-ap-ops/rdmfs:20211221

sudo npm install -g yarn

# install TLJH
curl https://raw.githubusercontent.com/jupyterhub/the-littlest-jupyterhub/master/bootstrap/bootstrap.py \
  | sudo python3 - \
    --admin test:test \
    --plugin git+https://github.com/RCOSDP/CS-tljh-repo2docker.git@master

# fix to use the RCOSDP's one as binderhub package.
sudo /opt/tljh/hub/bin/python -m pip install --upgrade git+https://github.com/RCOSDP/CS-binderhub.git
# restart TLJH
sudo systemctl restart jupyterhub
```

Refer to [The Littlest JupyterHub documentation](http://tljh.jupyter.org/en/latest/topic/customizing-installer.html?highlight=plugins#installing-tljh-plugins)
for more info on installing TLJH plugins.


## Usage

### List the environments

The *Environments* page shows the list of built environments, as well as the ones currently being built:

![environments](https://user-images.githubusercontent.com/591645/80962805-056df500-8e0e-11ea-81ab-6efc1c97432d.png)

### Add a new environment

Just like on [Binder](https://mybinder.org), new environments can be added by clicking on the *Add New* button and providing a URL to the repository. Optional names, memory, and CPU limits can also be set for the environment:

![add-new](https://user-images.githubusercontent.com/591645/80963115-9fce3880-8e0e-11ea-890b-c9b928f7edb1.png)

### Follow the build logs

Clicking on the *Logs* button will open a new dialog with the build logs:

![logs](https://user-images.githubusercontent.com/591645/82306574-86f18580-99bf-11ea-984b-4749ddde15e7.png)

### Select an environment

Once ready, the environments can be selected from the JupyterHub spawn page:

![select-env](https://user-images.githubusercontent.com/591645/81152248-10e22d00-8f82-11ea-9b5f-5831d8f7d085.png)

### Private Repositories

`tljh-repo2docker` also supports building environments from private repositories.

It is possible to provide the `username` and `password` in the `Credentials` section of the form:

![image](https://user-images.githubusercontent.com/591645/107362654-51567480-6ad9-11eb-93be-74d3b1c37828.png)

On GitHub and GitLab, a user might have to first create an access token with `read` access to use as the password:

![image](https://user-images.githubusercontent.com/591645/107350843-39c3bf80-6aca-11eb-8b82-6fa95ba4c7e4.png)

### Extra documentation

`tljh-repo2docker` is currently developed as part of the [Plasma project](https://github.com/plasmabio/plasma).

See the [Plasma documentation on user environments](https://docs.plasmabio.org/en/latest/environments/index.html) for more info.

## Building JupyterHub-ready images

See: https://repo2docker.readthedocs.io/en/latest/howto/jupyterhub_images.html

## Run Locally

Check out the instructions in [CONTRIBUTING.md](./CONTRIBUTING.md) to setup a local environment.
