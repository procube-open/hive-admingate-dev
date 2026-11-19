import importlib.util
import subprocess
from pathlib import Path

import pytest
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "apply_web_guard_templates",
    ROOT / "roles/oidc-init/files/apply-web-guard-templates.py",
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_nginx_limits_use_a_global_key_not_an_ingress_address():
    template = Environment(undefined=StrictUndefined).from_string(
        (ROOT / "roles/oidc-init/templates/web-access-guard.conf.template.j2").read_text()
    )
    rendered = template.render(
        hive_nginx_web_guard_requests_per_second=200,
        hive_nginx_web_guard_request_burst=400,
        hive_nginx_web_guard_connections=1000,
        hive_nginx_web_guard_header_timeout_seconds=30,
        hive_nginx_web_guard_body_timeout_seconds=30,
    )
    assert 'default "web";' in rendered
    assert "limit_req_zone $hive_web_access_limit_key" in rendered
    assert "limit_conn_zone $hive_web_access_limit_key" in rendered
    assert "$remote_addr" not in rendered
    assert "$http_x_forwarded_for" not in rendered


@pytest.mark.parametrize("failure", ["syntax", "reload"])
def test_failed_nginx_configuration_preserves_previous_files(tmp_path, monkeypatch, failure):
    root = tmp_path / "nginx"
    live = root / "conf.d"
    templates = root / "templates"
    candidate = tmp_path / "candidate"
    live.mkdir(parents=True)
    templates.mkdir()
    candidate.mkdir()
    (root / "nginx.conf").write_text("http { include " + str(live) + "/*.conf; }\n")
    (live / "service.conf").write_text("original")
    (live / guard.GUARD_CONF).write_text("original guard")
    (templates / "service.conf.template").write_text("original template")
    (templates / guard.GUARD_TEMPLATE).write_text("original guard template")
    (candidate / "service.conf.template").write_text("new template")
    calls = []

    def fake_run(args, env=None, check=True):
        calls.append(args)
        if args == ["entrypoint"]:
            stage = Path(env["NGINX_ENVSUBST_OUTPUT_DIR"])
            (stage / "service.conf").write_text("new config")
            return
        if (failure == "syntax" and args[:2] == ["nginx", "-t"]) or (
            failure == "reload" and args[:2] == ["nginx", "-s"]
        ):
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(guard.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        guard.apply("disable", candidate, root=root, entrypoint="entrypoint")
    assert (live / "service.conf").read_text() == "original"
    assert (live / guard.GUARD_CONF).read_text() == "original guard"
    assert (templates / "service.conf.template").read_text() == "original template"
    assert (templates / guard.GUARD_TEMPLATE).read_text() == "original guard template"
    if failure == "syntax":
        assert not any(args[:2] == ["nginx", "-s"] for args in calls)


def test_disabling_nginx_guard_removes_rendered_config(tmp_path, monkeypatch):
    root = tmp_path / "nginx"
    live = root / "conf.d"
    templates = root / "templates"
    candidate = tmp_path / "candidate"
    live.mkdir(parents=True)
    templates.mkdir()
    candidate.mkdir()
    (root / "nginx.conf").write_text("http { include " + str(live) + "/*.conf; }\n")
    (live / guard.GUARD_CONF).write_text("guard")
    (templates / guard.GUARD_TEMPLATE).write_text("guard template")
    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: None)
    guard.apply("disable", candidate, root=root, entrypoint="entrypoint")
    assert not (live / guard.GUARD_CONF).exists()
    assert not (templates / guard.GUARD_TEMPLATE).exists()


def test_unchanged_nginx_config_does_not_reload(tmp_path, monkeypatch):
    root = tmp_path / "nginx"
    live = root / "conf.d"
    templates = root / "templates"
    candidate = tmp_path / "candidate"
    live.mkdir(parents=True)
    templates.mkdir()
    candidate.mkdir()
    (root / "nginx.conf").write_text("http { include " + str(live) + "/*.conf; }\n")
    calls = []
    monkeypatch.setattr(guard.subprocess, "run", lambda args, **kwargs: calls.append(args))
    assert not guard.apply("enable", candidate, root=root, entrypoint="entrypoint")
    assert not any(args[:2] == ["nginx", "-s"] for args in calls)
