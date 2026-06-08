#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
WORKSPACE_DIR=$(dirname "$SCRIPT_DIR")

echo "Bootstrapping hive Python environment in ${WORKSPACE_DIR}/.venv..."
bash "${WORKSPACE_DIR}/setup/scripts/bootstrap-hive-env.sh" "${WORKSPACE_DIR}" "${SCRIPT_DIR}/PyGithub.patch"

echo "Installing Ansible collections..."
"${WORKSPACE_DIR}/setup/scripts/install-collection.sh" "${WORKSPACE_DIR}"

echo "Post-create setup completed successfully!"