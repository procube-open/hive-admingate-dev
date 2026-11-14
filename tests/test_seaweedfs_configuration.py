import json
import os
from pathlib import Path
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("overrides", [
    {},
    {
        "seaweedfs_image": "chrislusf/seaweedfs:4.54",
        "seaweedfs_s3_bucket": "another-bucket",
        "seaweedfs_s3_region": "us-east-1",
        "seaweedfs_s3_storage_class": "STANDARD_IA",
        "seaweedfs_volume_size_limit_mb": 512,
        "seaweedfs_volume_max": 50,
        "seaweedfs_tiering_full_percent": 85,
        "seaweedfs_tiering_quiet_for": "48h",
        "seaweedfs_tiering_interval_minutes": 30,
    },
])
def test_seaweedfs_configuration_renders_consistently(tmp_path, overrides):
    template = ROOT / "roles/put-master-toml/templates/master.toml"
    master_path = tmp_path / "master.toml"
    services_path = tmp_path / "services.json"
    playbook = [{
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "vars_files": [str(ROOT / "inventory/group_vars/all.yml"), str(ROOT / "inventory/seaweedfs.yml")],
        "tasks": [
            {"ansible.builtin.template": {"src": str(template), "dest": str(master_path)}},
            {"ansible.builtin.copy": {"content": "{{ services | to_json }}", "dest": str(services_path)},
             "no_log": True},
        ],
    }]
    playbook_path = tmp_path / "playbook.json"
    playbook_path.write_text(json.dumps(playbook))
    config_path = tmp_path / "ansible.cfg"
    config_path.write_text("[defaults]\n")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "ANSIBLE_CONFIG": str(config_path),
        "AWS_ACCESS_KEY_ID": "test-key",
        "AWS_SECRET_ACCESS_KEY": "test-secret",
    }
    result = subprocess.run(
        ["ansible-playbook", "-i", "localhost,", str(playbook_path), "-e", json.dumps(overrides)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with master_path.open("rb") as file:
        master = tomllib.load(file)
    services = json.loads(services_path.read_text())
    defaults = {
        "seaweedfs_image": "chrislusf/seaweedfs:4.53",
        "seaweedfs_s3_bucket": "admingate-seaweedfs-tiering-test",
        "seaweedfs_s3_region": "ap-northeast-1",
        "seaweedfs_s3_storage_class": "STANDARD",
        "seaweedfs_volume_size_limit_mb": 256,
        "seaweedfs_volume_max": 100,
        "seaweedfs_tiering_full_percent": 95,
        "seaweedfs_tiering_quiet_for": "24h",
        "seaweedfs_tiering_interval_minutes": 17,
    } | overrides
    backend = master["storage"]["backend"]["s3"]["default"]
    assert backend["bucket"] == defaults["seaweedfs_s3_bucket"]
    assert backend["region"] == defaults["seaweedfs_s3_region"]
    assert backend["storage_class"] == defaults["seaweedfs_s3_storage_class"]
    maintenance = master["master"]["maintenance"]
    assert maintenance["sleep_minutes"] == defaults["seaweedfs_tiering_interval_minutes"]
    assert f"-fullPercent={defaults['seaweedfs_tiering_full_percent']}" in maintenance["scripts"]
    assert f"-quietFor={defaults['seaweedfs_tiering_quiet_for']}" in maintenance["scripts"]
    for service in services.values():
        assert service["image"]["from"] == defaults["seaweedfs_image"]
    volume = services["seaweedfs-volume"]
    assert volume["environment"]["SEAWEEDFS_TIER_BUCKET"] == backend["bucket"]
    assert volume["environment"]["AWS_DEFAULT_REGION"] == backend["region"]
    assert volume["environment"]["AWS_ACCESS_KEY_ID"] == "test-key"
    assert volume["environment"]["AWS_SECRET_ACCESS_KEY"] == "test-secret"
    assert f"-max={defaults['seaweedfs_volume_max']}" in volume["command"]
    master_service = services["seaweedfs-master"]
    assert master_service["environment"]["WEED_STORAGE_BACKEND_S3_DEFAULT_AWS_ACCESS_KEY_ID"] == "test-key"
    assert master_service["environment"]["WEED_STORAGE_BACKEND_S3_DEFAULT_AWS_SECRET_ACCESS_KEY"] == "test-secret"
    assert f"-volumeSizeLimitMB={defaults['seaweedfs_volume_size_limit_mb']}" in master_service["command"]
