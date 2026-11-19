import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from jinja2 import Environment, StrictUndefined


ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "web_access_guard", ROOT / "roles/web-access-guard/files/web_access_guard.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def example_policy():
    return {
        "interfaces": ["eth0"],
        "ports": [80, 443, 10443, 13000, 18081],
        "ipv4_cidrs": ["203.0.113.0/24", "192.0.2.0/24"],
        "ipv6_cidrs": ["2001:db8:1::/48", "2001:db8:2::/48"],
        "ipv4_min_networks": 1,
        "ipv6_min_networks": 1,
        "min_update_ratio": 0.8,
        "new_connections_per_second": 20,
        "new_connections_burst": 40,
        "connections_per_ip": 100,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interfaces", "eth0"),
        ("interfaces", []),
        ("ports", [80, 0]),
        ("ports", [80, 80]),
        ("ipv4_cidrs", []),
        ("ipv6_cidrs", ["192.0.2.0/24"]),
        ("ipv4_cidrs", ["0.0.0.0/0"]),
        ("ipv4_cidrs", ["192.0.2.1/24"]),
        ("new_connections_per_second", 0),
        ("min_update_ratio", 0),
    ],
)
def test_rejects_invalid_policy(field, value):
    policy = example_policy()
    policy[field] = value
    with pytest.raises(ValueError):
        guard.validate(policy)


@pytest.mark.parametrize("version", [4, 6])
def test_generated_rules_cover_ports_before_dnat_without_accepting_other_traffic(version):
    policy = guard.validate(example_policy())
    base, chain, target, restore, rules, hook = guard.commands(policy, version, "1234567890")
    assert base[:4] == ["iptables" if version == 4 else "ip6tables", "-w", "-t", "mangle"]
    assert hook[-1] == chain
    assert "family inet6" in restore[0] if version == 6 else "family inet " in restore[0]
    assert len(rules) == 3
    for rule in rules:
        assert rule[rule.index("-i") + 1] == "eth0"
        assert rule[rule.index("--dports") + 1] == "80,443,10443,13000,18081"
        assert rule[rule.index("--dst-type") + 1] == "LOCAL"
        assert rule[rule.index("--ctstate") + 1] == "NEW"
        assert rule[-2:] == ["-j", "DROP"]
    assert rules[0][rules[0].index("--match-set") + 1] == target


@pytest.mark.parametrize(("country", "ddos", "matches"), [
    (True, False, ["set"]),
    (False, True, ["connlimit", "hashlimit"]),
    (True, True, ["set", "connlimit", "hashlimit"]),
])
def test_policy_builds_only_enabled_rules(country, ddos, matches):
    raw = dict(example_policy(), country_enabled=country, ddos_enabled=ddos)
    if not country:
        del raw["ipv4_cidrs"]
        del raw["ipv6_cidrs"]
    if not ddos:
        del raw["connections_per_ip"]
    for version in (4, 6):
        _, _, target, restore, rules, _ = guard.commands(guard.validate(raw), version, "1234567890")
        assert bool(target) == bool(restore) == country
        assert [match for rule in rules for match in ("set", "connlimit", "hashlimit") if match in rule] == matches


def test_ddos_only_template_does_not_read_country_files():
    env = Environment(undefined=StrictUndefined)
    env.filters["bool"] = bool
    env.filters["to_json"] = json.dumps
    template = env.from_string((ROOT / "roles/web-access-guard/templates/policy.json.j2").read_text())
    policy = example_policy()
    policy.update(country_enabled=False, ddos_enabled=True)
    raw = json.loads(template.render(**{"hive_web_access_guard_" + k: v for k, v in policy.items()}))
    assert "ipv4_cidrs" not in raw and "ipv6_cidrs" not in raw
    assert guard.validate(raw)["ddos_enabled"]


def test_disabling_both_replaces_legacy_policy_without_attaching_hooks(tmp_path, monkeypatch):
    state = tmp_path / "policy.json"
    state.write_text(json.dumps(example_policy()))
    monkeypatch.setattr(guard, "old_hooks", lambda binary: [
        ["-j", "HWAG{}_1234567890".format(4 if binary == "iptables" else 6)]
    ])
    calls = []
    monkeypatch.setattr(guard, "run", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(guard, "destroy_set_if_present", lambda target: None)
    disabled = guard.validate({"country_enabled": False, "ddos_enabled": False})
    assert guard.apply(disabled, state)
    assert json.loads(state.read_text()) == disabled
    assert sum(call[4:6] == ["-D", "PREROUTING"] for call in calls) == 2
    assert not any("-I" in call or "-A" in call for call in calls)


def test_failed_second_hook_preserves_old_policy(tmp_path, monkeypatch):
    policy = guard.validate(example_policy())
    state = tmp_path / "policy.json"
    old = dict(policy, connections_per_ip=50)
    state.write_text(json.dumps(old))
    calls = []

    def fake_run(args, input_text=None):
        calls.append(args)
        if args[:5] == ["ip6tables", "-w", "-t", "mangle", "-I"]:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(guard, "run", fake_run)
    monkeypatch.setattr(guard, "old_hooks", lambda binary: [])
    with pytest.raises(subprocess.CalledProcessError):
        guard.apply(policy, state)
    assert json.loads(state.read_text()) == old
    assert any(call[:5] == ["iptables", "-w", "-t", "mangle", "-D"] for call in calls)
    assert sum(call[:2] == ["ipset", "destroy"] for call in calls) == 2


def test_initial_apply_prepares_both_families_before_attaching(tmp_path, monkeypatch):
    policy = guard.validate(example_policy())
    state = tmp_path / "policy.json"
    calls = []
    monkeypatch.setattr(guard, "run", lambda args, input_text=None: calls.append(args))
    monkeypatch.setattr(guard, "old_hooks", lambda binary: [])
    assert guard.apply(policy, state)
    assert json.loads(state.read_text()) == policy
    sets = [i for i, call in enumerate(calls) if call[:2] == ["ipset", "restore"]]
    hooks = [i for i, call in enumerate(calls) if call[4:6] == ["-I", "PREROUTING"]]
    assert len(sets) == len(hooks) == 2
    assert max(sets) < min(hooks)


def test_failed_old_hook_removal_restores_previous_policy(tmp_path, monkeypatch):
    policy = guard.validate(example_policy())
    old = dict(policy, connections_per_ip=50)
    state = tmp_path / "policy.json"
    state.write_text(json.dumps(old))
    hooks = {
        "iptables": ["-m", "comment", "--comment", guard.TAG + "1111111111", "-j", "HWAG4_1111111111"],
        "ip6tables": ["-m", "comment", "--comment", guard.TAG + "2222222222", "-j", "HWAG6_2222222222"],
    }
    calls = []

    def fake_run(args, input_text=None):
        calls.append(args)
        if args == ["ip6tables", "-w", "-t", "mangle", "-D", "PREROUTING"] + hooks["ip6tables"]:
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(guard, "run", fake_run)
    monkeypatch.setattr(guard, "old_hooks", lambda binary: [hooks[binary]])
    with pytest.raises(subprocess.CalledProcessError):
        guard.apply(policy, state)
    assert json.loads(state.read_text()) == old
    assert ["iptables", "-w", "-t", "mangle", "-I", "PREROUTING", "1"] + hooks["iptables"] in calls


def test_large_dataset_shrink_is_rejected_before_rule_changes(tmp_path, monkeypatch):
    previous = guard.validate(example_policy())
    state = tmp_path / "policy.json"
    state.write_text(json.dumps(previous))
    new = example_policy()
    new["ipv4_cidrs"] = new["ipv4_cidrs"][:1]
    monkeypatch.setattr(guard, "run", lambda *args: pytest.fail("must not change firewall"))
    with pytest.raises(ValueError, match="shrank"):
        guard.apply(guard.validate(new), state)
    assert json.loads(state.read_text()) == previous


def test_removal_touches_only_valid_owned_chains(monkeypatch):
    calls = []
    monkeypatch.setattr(guard, "run", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(guard.shutil, "which", lambda binary: binary)
    monkeypatch.setattr(guard, "output", lambda args: "hwag4_1234567890\n")
    hook = ["-m", "comment", "--comment", guard.TAG + "1234567890", "-j", "HWAG4_1234567890"]
    guard.remove_hooks(4, [hook])
    assert calls[-1] == ["ipset", "destroy", "hwag4_1234567890"]
    calls.clear()
    with pytest.raises(ValueError, match="unexpected"):
        guard.remove_hooks(4, [hook[:-1] + ["DOCKER"]])
    assert calls == []
