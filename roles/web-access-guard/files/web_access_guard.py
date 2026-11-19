#!/usr/bin/env python3
"""Install a host-side ingress policy without modifying Docker-owned chains."""

import argparse
import fcntl
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


TAG = "hive-web-access-guard:"
CHAIN_PREFIX = "HWAG"
SET_PREFIX = "hwag"


def validate(raw):
    interfaces = raw.get("interfaces", [])
    ports = raw.get("ports", [])
    if not isinstance(interfaces, list) or not interfaces or any(
        not isinstance(i, str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", i)
        for i in interfaces
    ):
        raise ValueError("one or more valid external interfaces are required")
    if not isinstance(ports, list) or not ports or len(ports) > 15 or any(
        isinstance(p, bool) or not isinstance(p, int) or p < 1 or p > 65535
        for p in ports
    ):
        raise ValueError("one to fifteen valid TCP ports are required")
    if len(set(interfaces)) != len(interfaces) or len(set(ports)) != len(ports):
        raise ValueError("duplicate interfaces or ports")
    for key in ("new_connections_per_second", "new_connections_burst", "connections_per_ip"):
        if isinstance(raw.get(key), bool) or not isinstance(raw.get(key), int) or raw[key] < 1:
            raise ValueError("{} must be a positive integer".format(key))
    for key in ("ipv4_min_networks", "ipv6_min_networks"):
        if isinstance(raw.get(key), bool) or not isinstance(raw.get(key), int) or raw[key] < 1:
            raise ValueError("{} must be a positive integer".format(key))
    ratio = raw.get("min_update_ratio")
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 < ratio <= 1:
        raise ValueError("min_update_ratio must be greater than zero and at most one")
    result = {
        "interfaces": sorted(interfaces),
        "ports": sorted(ports),
        "new_connections_per_second": raw["new_connections_per_second"],
        "new_connections_burst": raw["new_connections_burst"],
        "connections_per_ip": raw["connections_per_ip"],
        "ipv4_min_networks": raw["ipv4_min_networks"],
        "ipv6_min_networks": raw["ipv6_min_networks"],
        "min_update_ratio": ratio,
    }
    for version in (4, 6):
        key = "ipv{}_cidrs".format(version)
        entries = raw.get(key)
        if not isinstance(entries, list) or not entries:
            raise ValueError("{} must contain at least one network".format(key))
        networks = []
        for entry in entries:
            if not isinstance(entry, str):
                raise ValueError("{} must contain strings".format(key))
            network = ipaddress.ip_network(entry, strict=True)
            if network.version != version or network.prefixlen == 0:
                raise ValueError("invalid network in {}: {}".format(key, entry))
            networks.append(network)
        result[key] = [str(n) for n in ipaddress.collapse_addresses(networks)]
        if len(result[key]) < result["ipv{}_min_networks".format(version)]:
            raise ValueError("{} has fewer networks than its configured minimum".format(key))
    return result


def run(args, input_text=None):
    subprocess.run(args, input=input_text, text=True, check=True, stdout=subprocess.PIPE)


def output(args):
    return subprocess.check_output(args, text=True)


def old_hooks(binary):
    result = []
    for line in output([binary, "-w", "-t", "mangle", "-S", "PREROUTING"]).splitlines():
        rule = shlex.split(line)
        if len(rule) >= 2 and rule[:2] == ["-A", "PREROUTING"]:
            if "--comment" in rule and rule[rule.index("--comment") + 1].startswith(TAG):
                result.append(rule[2:])
    return result


def commands(policy, version, suffix):
    binary = "iptables" if version == 4 else "ip6tables"
    chain = "{}{}_{}".format(CHAIN_PREFIX, version, suffix)
    target = "{}{}_{}".format(SET_PREFIX, version, suffix)
    family = "inet" if version == 4 else "inet6"
    base = [binary, "-w", "-t", "mangle"]
    entries = policy["ipv{}_cidrs".format(version)]
    restore = ["create {} hash:net family {} maxelem {}".format(target, family, max(65536, len(entries) * 2))]
    restore.extend("add {} {}".format(target, entry) for entry in entries)
    selectors = [
        "-p", "tcp", "-m", "multiport", "--dports",
        ",".join(str(p) for p in policy["ports"]),
        "-m", "addrtype", "--dst-type", "LOCAL",
    ]
    rules = []
    for interface in policy["interfaces"]:
        prefix = ["-i", interface] + selectors + ["-m", "conntrack", "--ctstate", "NEW"]
        rules.append(prefix + ["-m", "set", "!", "--match-set", target, "src", "-j", "DROP"])
        syn = prefix + ["--syn"]
        rules.append(syn + [
            "-m", "connlimit", "--connlimit-above", str(policy["connections_per_ip"]),
            "--connlimit-mask", "32" if version == 4 else "128", "-j", "DROP",
        ])
        rules.append(syn + [
            "-m", "hashlimit", "--hashlimit-above",
            "{}/second".format(policy["new_connections_per_second"]),
            "--hashlimit-burst", str(policy["new_connections_burst"]),
            "--hashlimit-mode", "srcip", "--hashlimit-srcmask", "32" if version == 4 else "128",
            "--hashlimit-name", "{}{}_{}".format(SET_PREFIX, version, suffix[:7]),
            "-j", "DROP",
        ])
    hook = ["-m", "comment", "--comment", TAG + suffix, "-j", chain]
    return base, chain, target, restore, rules, hook


def atomic_write(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".policy-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def managed_chains(version, hooks):
    chains = {}
    for hook in hooks:
        if "-j" not in hook:
            raise ValueError("invalid managed hook")
        chain = hook[hook.index("-j") + 1]
        match = re.fullmatch(r"{}{}_([0-9a-f]{{10}})".format(CHAIN_PREFIX, version), chain)
        if not match:
            raise ValueError("unexpected managed chain: {}".format(chain))
        chains[chain] = "{}{}_{}".format(SET_PREFIX, version, match.group(1))
    return chains


def remove_hooks(version, hooks):
    binary = "iptables" if version == 4 else "ip6tables"
    base = [binary, "-w", "-t", "mangle"]
    chains = managed_chains(version, hooks)
    for hook in hooks:
        run(base + ["-D", "PREROUTING"] + hook)
    for chain, target in chains.items():
        run(base + ["-F", chain])
        run(base + ["-X", chain])
        run(["ipset", "destroy", target])


def apply(policy, state_file):
    previous = {}
    old_chains = {}
    created = []
    attached = []
    detached = []
    suffix = uuid.uuid4().hex[:10]
    try:
        if state_file.exists():
            saved = validate(json.loads(state_file.read_text()))
            for version in (4, 6):
                key = "ipv{}_cidrs".format(version)
                if len(policy[key]) < len(saved[key]) * policy["min_update_ratio"]:
                    raise ValueError("{} shrank below the configured update ratio".format(key))
            if saved == policy:
                complete = True
                for version in (4, 6):
                    binary = "iptables" if version == 4 else "ip6tables"
                    hooks = old_hooks(binary)
                    if len(hooks) != 1:
                        complete = False
                        break
                    chain = hooks[0][hooks[0].index("-j") + 1]
                    match = re.fullmatch(r"{}{}_([0-9a-f]{{10}})".format(CHAIN_PREFIX, version), chain)
                    if not match:
                        complete = False
                        break
                    try:
                        output([binary, "-w", "-t", "mangle", "-S", chain])
                        output(["ipset", "list", "{}{}_{}".format(SET_PREFIX, version, match.group(1))])
                    except subprocess.CalledProcessError:
                        complete = False
                        break
                if complete:
                    return False
        for version in (4, 6):
            base, chain, target, restore, rules, hook = commands(policy, version, suffix)
            previous[version] = old_hooks(base[0])
            old_chains[version] = managed_chains(version, previous[version])
            created.append((base, chain, target))
            run(["ipset", "restore"], "\n".join(restore) + "\n")
            run(base + ["-N", chain])
            for rule in rules:
                run(base + ["-A", chain] + rule)
        for version in (4, 6):
            base, chain, target, restore, rules, hook = commands(policy, version, suffix)
            run(base + ["-I", "PREROUTING", "1"] + hook)
            attached.append((base, hook))
        for version in (4, 6):
            binary = "iptables" if version == 4 else "ip6tables"
            base = [binary, "-w", "-t", "mangle"]
            for hook in previous[version]:
                run(base + ["-D", "PREROUTING"] + hook)
                detached.append((base, hook))
        atomic_write(state_file, policy)
    except Exception:
        for base, hook in reversed(detached):
            run(base + ["-I", "PREROUTING", "1"] + hook)
        for base, hook in reversed(attached):
            run(base + ["-D", "PREROUTING"] + hook)
        for base, chain, target in reversed(created):
            try:
                run(base + ["-F", chain])
                run(base + ["-X", chain])
            except subprocess.CalledProcessError:
                pass
            try:
                run(["ipset", "destroy", target])
            except subprocess.CalledProcessError:
                pass
        raise
    for version in (4, 6):
        binary = "iptables" if version == 4 else "ip6tables"
        base = [binary, "-w", "-t", "mangle"]
        for chain, target in old_chains[version].items():
            try:
                run(base + ["-F", chain])
                run(base + ["-X", chain])
                run(["ipset", "destroy", target])
            except subprocess.CalledProcessError as error:
                print("web-access-guard: unable to clean old chain: {}".format(error), file=sys.stderr)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if args.remove and (args.config or args.validate_only):
        parser.error("--remove cannot be combined with --config or --validate-only")
    if not args.remove and not args.config:
        parser.error("--config is required unless --remove is specified")
    policy = None if args.remove else validate(json.loads(args.config.read_text()))
    if args.validate_only:
        return
    args.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(str(args.state) + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.remove:
            for version in (4, 6):
                binary = "iptables" if version == 4 else "ip6tables"
                remove_hooks(version, old_hooks(binary))
        else:
            print("changed" if apply(policy, args.state) else "unchanged")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print("web-access-guard: {}".format(error), file=sys.stderr)
        sys.exit(1)
