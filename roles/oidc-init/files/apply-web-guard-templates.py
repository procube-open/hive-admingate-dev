#!/usr/bin/env python3
"""Render and validate all Nginx templates before replacing live configuration."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


GUARD_CONF = "hive-web-access-guard.conf"
GUARD_TEMPLATE = GUARD_CONF + ".template"


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".hive-nginx-", dir=str(destination.parent))
    os.close(fd)
    try:
        shutil.copy2(str(source), name)
        os.replace(name, str(destination))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply(mode, templates, root=Path("/etc/nginx"), entrypoint="/docker-entrypoint.d/20-envsubst-on-templates.sh"):
    if mode not in ("enable", "disable"):
        raise ValueError("expected enable or disable")
    live = root / "conf.d"
    live_templates = root / "templates"
    with tempfile.TemporaryDirectory(prefix="hive-nginx-guard-") as directory:
        work = Path(directory)
        stage = work / "conf.d"
        backup = work / "backup"
        for parent in (live, live_templates, templates):
            for path in parent.rglob("*"):
                if path.is_symlink():
                    raise ValueError("symlinks are not supported in {}".format(parent))
        shutil.copytree(str(live), str(stage))
        shutil.copytree(str(live), str(backup / "conf.d"))
        shutil.copytree(str(live_templates), str(backup / "templates"))
        if mode == "disable":
            (stage / GUARD_CONF).unlink(missing_ok=True)
        environment = os.environ.copy()
        environment["NGINX_ENVSUBST_OUTPUT_DIR"] = str(stage)
        environment["NGINX_ENVSUBST_TEMPLATE_DIR"] = str(templates)
        subprocess.run([entrypoint], env=environment, check=True)
        config = (root / "nginx.conf").read_text()
        include = "include {}/conf.d/*.conf;".format(root)
        if include not in config:
            raise ValueError("Nginx conf.d include not found")
        (work / "nginx.conf").write_text(config.replace(include, "include {}/*.conf;".format(stage)))
        subprocess.run(["nginx", "-t", "-c", str(work / "nginx.conf")], check=True)

        staged = [
            (path, live / path.relative_to(stage), backup / "conf.d" / path.relative_to(stage))
            for path in stage.rglob("*") if path.is_file()
        ]
        staged.extend(
            (path, live_templates / path.relative_to(templates), backup / "templates" / path.relative_to(templates))
            for path in templates.rglob("*") if path.is_file()
        )
        replacements = [
            (source, target, original)
            for source, target, original in staged
            if not target.is_file() or target.read_bytes() != source.read_bytes()
        ]
        removals = []
        if mode == "disable":
            removals = [
                (live / GUARD_CONF, backup / "conf.d" / GUARD_CONF),
                (live_templates / GUARD_TEMPLATE, backup / "templates" / GUARD_TEMPLATE),
            ]
            removals = [(target, original) for target, original in removals if target.exists()]
        if not replacements and not removals:
            return False
        changed = []
        try:
            for source, target, original in replacements:
                changed.append((target, original))
                atomic_copy(source, target)
            for target, original in removals:
                changed.append((target, original))
                target.unlink()
            subprocess.run(["nginx", "-s", "reload"], check=True)
        except Exception:
            for target, original in reversed(changed):
                if original.is_file():
                    atomic_copy(original, target)
                elif target.exists():
                    target.unlink()
            raise
        return True


if __name__ == "__main__":
    try:
        changed = apply(sys.argv[1], Path(sys.argv[2]))
        print("hive-web-guard: changed" if changed else "hive-web-guard: unchanged")
    except (IndexError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print("web-access-guard: {}".format(error), file=sys.stderr)
        sys.exit(1)
