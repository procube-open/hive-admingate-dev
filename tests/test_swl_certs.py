import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
import yaml


ROLE_TASKS = Path(__file__).resolve().parents[1] / "roles/swl-certs/tasks/main.yml"
PING = "/admin/api/ping"
LOOKUP = "/api/client/swl"
ADD = "/admin/api/client/add"
REVOKE = "/admin/api/client/revoke"
SECRET = "/admin/api/secret/create"
CERTIFICATE = "certificate-generation-reached"
ACTIVE_STATES = ["ISSUABLE", "ISSUED", "UPDATABLE", "PENDING"]


@pytest.fixture
def run_role(tmp_path):
    def run(client="null", responses=None, native=False):
        calls = []
        responses = responses or {}

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self):
                calls.append(self.path)
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                status, body = responses.get(
                    self.path,
                    (200, "pong" if self.path == PING else client)
                    if self.command == "GET"
                    else (201 if self.path == SECRET else 200, "{}"),
                )
                self.send_response(status)
                # The real API may return JSON with a text/plain content type.
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(body.encode())

            do_GET = handle_request
            do_POST = handle_request

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            tasks = yaml.safe_load(ROLE_TASKS.read_text())
            for index, task in enumerate(tasks):
                if "uri" in task:
                    task["uri"]["url"] = task["uri"]["url"].replace(
                        "http://localhost:3000",
                        f"http://127.0.0.1:{server.server_port}",
                    )
                    task["uri"]["use_proxy"] = False
                    if task["uri"]["url"].endswith(SECRET):
                        task["no_log"] = True
                    if "until" in task:
                        task["retries"] = 1
                        task["delay"] = 0
                elif "shell" in task or "file" in task or "copy" in task:
                    tasks[index] = {
                        "name": task["name"],
                        "debug": {
                            "msg": CERTIFICATE
                            if task["name"].startswith("Exec scepclient-swl")
                            else "non-API operation"
                        },
                    }

            playbook = tmp_path / "playbook.yml"
            playbook.write_text(yaml.safe_dump([{
                "hosts": "localhost",
                "gather_facts": False,
                "tasks": tasks,
            }]))
            result = subprocess.run(
                [
                    shutil.which("ansible-playbook") or "ansible-playbook",
                    "-i", "localhost,", "-c", "local",
                    "-e", f"ansible_python_interpreter={sys.executable}",
                    str(playbook),
                ],
                env={
                    **os.environ,
                    "ANSIBLE_JINJA2_NATIVE": str(native),
                    "ANSIBLE_NOCOLOR": "1",
                    "ANSIBLE_LOCAL_TEMP": str(tmp_path / "ansible"),
                },
                text=True, capture_output=True, timeout=120,
            )
            return result, calls
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    return run


@pytest.mark.parametrize("native", [False, True], ids=["legacy-jinja", "native-jinja"])
@pytest.mark.parametrize("status", [None, "INACTIVE", *ACTIVE_STATES])
def test_client_state_branching(run_role, status, native):
    client = json.dumps(None if status is None else {"uid": "swl", "status": status})
    result, calls = run_role(client, native=native)
    mutation = [ADD] if status is None else [REVOKE] if status in ACTIVE_STATES else []
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [PING, LOOKUP, *mutation, SECRET]
    assert CERTIFICATE in result.stdout
    assert f"changed={len(mutation) + 1}" in result.stdout


@pytest.mark.parametrize("client", [
    "",
    "not-json",
    '{"uid":',
    '"null"',
    '"{\\"uid\\": \\"swl\\", \\"status\\": \\"INACTIVE\\"}"',
    '""',
    "false",
    "0",
    "[]",
    '[{"uid": "swl", "status": "INACTIVE"}]',
    "{}",
    '{"uid": "swl"}',
    '{"status": "INACTIVE"}',
    '{"uid": "other", "status": "INACTIVE"}',
    '{"uid": "swl", "status": "UNKNOWN"}',
    '{"uid": "swl", "status": null}',
    '{"uid": "swl", "status": []}',
])
def test_invalid_lookup_stops_before_mutations(run_role, client):
    result, calls = run_role(client)
    assert result.returncode != 0
    assert calls == [PING, LOOKUP]
    assert CERTIFICATE not in result.stdout


@pytest.mark.parametrize("path,code,body", [
    (PING, 500, "unavailable"),
    (PING, 404, "not found"),
    (PING, 200, "not pong"),
    (LOOKUP, 500, "unavailable"),
    (LOOKUP, 404, "null"),
])
def test_failed_prerequisites_stop_before_mutations(run_role, path, code, body):
    result, calls = run_role(responses={path: (code, body)})
    assert result.returncode != 0
    assert calls == ([PING, PING] if path == PING else [PING, LOOKUP])
    assert CERTIFICATE not in result.stdout


@pytest.mark.parametrize("path,code", [
    (ADD, 500),
    (ADD, 400),
    (REVOKE, 500),
    (REVOKE, 404),
    (REVOKE, 400),
    (SECRET, 500),
])
def test_failed_mutations_are_not_retried(run_role, path, code):
    client = json.dumps({"uid": "swl", "status": "ISSUED"}) if path == REVOKE else "null"
    result, calls = run_role(client, responses={path: (code, "failure")})
    assert result.returncode != 0
    assert calls == [PING, LOOKUP, *([ADD] if path == SECRET else []), path]
    assert CERTIFICATE not in result.stdout
