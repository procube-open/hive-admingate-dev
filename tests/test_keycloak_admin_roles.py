import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit


PLAYBOOK = Path(__file__).resolve().parents[1] / "roles/prov-tools/files/playbooks/idpUser.yml"
ROLE = {"id": "role-id", "name": "realm-admin"}
BASE = "/admin/realms/webgate"
MAPPING = f"{BASE}/users/user-id/role-mappings/clients/client-id"


class KeycloakMock(BaseHTTPRequestHandler):
    assigned = False
    writes = []
    user = None

    def respond(self, status, data=None):
        body = json.dumps(data).encode() if data is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        responses = {
            f"{BASE}/users": [self.user] if self.user else [],
            f"{BASE}/users/user-id": self.user,
            f"{BASE}/users/user-id/groups": [],
            f"{BASE}/clients": [{"id": "client-id", "clientId": "realm-management"}],
            f"{BASE}/clients/client-id/roles": [ROLE],
            f"{MAPPING}/available": [] if self.assigned else [ROLE],
            f"{MAPPING}/composite": [ROLE] if self.assigned else [],
        }
        if path not in responses:
            return self.respond(404, {"path": self.path})
        self.respond(200, responses[path])

    def do_POST(self):
        if self.path == "/realms/master/protocol/openid-connect/token":
            return self.respond(200, {"access_token": "test-token", "token_type": "Bearer"})
        if self.path == f"{BASE}/users":
            user = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            type(self).user = {**user, "id": "user-id"}
            return self.respond(201)
        self.update_mapping(True)

    def do_PUT(self):
        if self.path == f"{BASE}/users/user-id":
            type(self).user = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            return self.respond(204)
        self.respond(404, {"path": self.path})

    def do_DELETE(self):
        if self.path == f"{BASE}/users/user-id":
            type(self).user = None
            type(self).assigned = False
            return self.respond(204)
        self.update_mapping(False)

    def update_mapping(self, assigned):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != MAPPING or body != [ROLE]:
            return self.respond(400, {"path": self.path, "body": body})
        type(self).assigned = assigned
        type(self).writes.append(self.command)
        self.respond(204)

    def log_message(self, format, *args):
        pass


def test_admin_role_provisioning(tmp_path):
    KeycloakMock.assigned = False
    KeycloakMock.writes = []
    KeycloakMock.user = {"id": "user-id", "username": "test-user"}
    inventory = tmp_path / "inventory"
    inventory.write_text("[users]\nlocalhost ansible_connection=local\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), KeycloakMock)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        for operation, idm_role, assigned, writes in [
            ("add", "IDM_USER", False, []),
            ("add", "IDM_ADMIN", True, ["POST"]),
            ("modify", "IDM_ADMIN", True, []),
            ("modify", "IDM_USER", False, ["DELETE"]),
            ("modify", "IDM_USER", False, []),
            ("modify", "IDM_ADMIN", True, ["POST"]),
        ]:
            KeycloakMock.writes = []
            variables = {
                "idp_url": f"http://127.0.0.1:{server.server_port}",
                "ansible_python_interpreter": sys.executable,
                "uid": "test-user",
                "prov_operation": operation,
                "idmRole": idm_role,
            }
            result = subprocess.run(
                [
                    "ansible-playbook", "-i", str(inventory), "-e", json.dumps(variables),
                    "--start-at-task", "Sync webgate realm administrator role", str(PLAYBOOK),
                ],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert KeycloakMock.assigned is assigned
            assert KeycloakMock.writes == writes
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_user_provisioning(tmp_path):
    KeycloakMock.user = None
    KeycloakMock.assigned = False
    inventory = tmp_path / "inventory"
    inventory.write_text("[users]\nlocalhost ansible_connection=local\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), KeycloakMock)
    thread = Thread(target=server.serve_forever)
    thread.start()

    try:
        for operation, role in [("add", "IDM_ADMIN"), ("modify", "IDM_USER"), ("delete", "IDM_USER")]:
            variables = {
                "idp_url": f"http://127.0.0.1:{server.server_port}",
                "ansible_python_interpreter": sys.executable,
                "uid": "test-user",
                "cn": "Test",
                "sn": "User",
                "email": "test@example.test",
                "team": ["team1"],
                "prov_operation": operation,
                "idmRole": role,
                "accountLock": operation == "modify",
            }
            result = subprocess.run(
                ["ansible-playbook", "-i", str(inventory), "-e", json.dumps(variables), str(PLAYBOOK)],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            if operation == "delete":
                assert KeycloakMock.user is None
            else:
                assert KeycloakMock.user["attributes"]["IDMRole"] == [role]
                assert KeycloakMock.user["enabled"] is (operation != "modify")
                assert KeycloakMock.user["requiredActions"] == ["UPDATE_PASSWORD", "CONFIGURE_TOTP"]
                assert KeycloakMock.assigned is (role == "IDM_ADMIN")
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
