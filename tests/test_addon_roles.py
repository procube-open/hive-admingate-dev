from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class TestAddonRoles(unittest.TestCase):
    def load_tasks(self, role):
        path = ROOT / "roles" / role / "tasks" / "main.yml"
        return yaml.safe_load(path.read_text())

    def test_addon_keeps_preparation_without_image_pull(self):
        tasks = self.load_tasks("addon")
        imports = [
            task["import_role"]["name"] for task in tasks if "import_role" in task
        ]
        self.assertEqual(imports, ["selenium-node-docker"])
        self.assertEqual(
            [task["copy"]["dest"] for task in tasks if "copy" in task],
            [
                "/etc/docker/certs.d/{{ ns_container_repository }}/client.cert",
                "/etc/docker/certs.d/{{ ns_container_repository }}/client.key",
            ],
        )

    def test_addon2_imports_image_pull(self):
        self.assertEqual(
            self.load_tasks("addon2"),
            [{"import_role": {"name": "pull-docker-images"}}],
        )
