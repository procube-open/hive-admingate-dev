#!/bin/bash
set -euo pipefail

workspace_dir=$1
patch_file=$2
venv_dir="${workspace_dir}/.venv"
bashrc_path="/home/vscode/.bashrc"
bashrc_marker_begin="# >>> hive-builder workspace venv >>>"
bashrc_marker_end="# <<< hive-builder workspace venv <<<"

echo "Creating Python virtual environment at ${venv_dir}..."
python3 -m venv "${venv_dir}"

echo "Upgrading pip..."
"${venv_dir}/bin/pip" install --upgrade pip

echo "Installing Python packages..."
# ansible-core>=2.19.0 でyamlのパースに失敗するため、バージョンを下げる
"${venv_dir}/bin/pip" install \
    "ansible-core<2.19.0" \
    ansible-dev-tools \
    setuptools \
    hive-builder \
    inquirer \
    google-cloud-compute \
    "PyGithub==2.5.0"

echo "Applying PyGithub patch..."
pygithub_location=$("${venv_dir}/bin/pip" show PyGithub | grep Location: | awk '{print $2}')
if patch --forward --dry-run "${pygithub_location}/github/Repository.py" < "${patch_file}" > /dev/null 2>&1; then
    patch --forward "${pygithub_location}/github/Repository.py" < "${patch_file}"
else
    echo "PyGithub patch already applied or not required."
fi

echo "Configuring shell PATH and hive completion..."
if grep -Fq "${bashrc_marker_begin}" "${bashrc_path}"; then
    sed -i "/${bashrc_marker_begin}/,/${bashrc_marker_end}/d" "${bashrc_path}"
fi

cat >> "${bashrc_path}" <<EOF

${bashrc_marker_begin}
if [ -d "${venv_dir}/bin" ]; then
    export PATH="${venv_dir}/bin:\$PATH"
fi

if command -v hive > /dev/null 2>&1; then
    source "\$(hive get-install-dir)/hive-completion.sh" 2>/dev/null
fi
${bashrc_marker_end}
EOF