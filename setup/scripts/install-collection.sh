#!/bin/bash
set -euo pipefail

workspace_folder=$1
venv_dir="${workspace_folder}/.venv"
pip_bin="${venv_dir}/bin/pip"
ansible_galaxy_bin="${venv_dir}/bin/ansible-galaxy"

# Install the collection with the workspace-local virtual environment.
"${ansible_galaxy_bin}" collection install -r "$("${pip_bin}" show hive-builder | grep Location: | awk '{print $2}')/hive_builder/requirements.yml" -p "${workspace_folder}/.collections"
"${pip_bin}" install -r "${workspace_folder}/.collections/ansible_collections/azure/azcollection/requirements.txt"
