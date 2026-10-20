"""Run only read-only preflights, with a synthetic PATH. Never modify the host."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "linux" / "setup-permissions.sh"


@pytest.fixture
def host(tmp_path):
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "calls"
    env = {**os.environ, "PATH": str(commands), "SETUP_TEST_COMMAND_LOG": str(log)}

    def stub(name, result="", code=0):
        target = commands / name
        target.write_text(
            f"#!/bin/bash\nprintf '%s\\n' '{name}' >> \"$SETUP_TEST_COMMAND_LOG\"\n"
            f"printf '%s\\n' '{result}'\nexit {code}\n"
        )
        target.chmod(0o755)

    (commands / "dirname").symlink_to(shutil.which("dirname"))
    stub("uname", "Linux")
    stub("id", "1000")
    for command in ("systemctl", "udevadm", "install", "cmp", "modprobe"):
        stub(command)
    # Keep even preflight reads away from real /etc, which may already contain
    # administrator-managed or symlinked rules on the machine running the tests.
    setup = tmp_path / "linux"
    setup.mkdir()
    text = SCRIPT.read_text().replace("/etc/udev/rules.d", str(tmp_path / "etc" / "rules"))
    text = text.replace("/etc/modules-load.d", str(tmp_path / "etc" / "modules"))
    script = setup / SCRIPT.name
    script.write_text(text)
    for name in (
        "70-open-shinkansen.rules",
        "70-open-shinkansen-uinput.rules",
        "open-shinkansen.conf",
    ):
        shutil.copyfile(ROOT / "linux" / name, setup / name)
    return SimpleHost(commands, env, log, stub, script)


class SimpleHost:
    def __init__(self, commands, env, log, stub, script):
        self.commands, self.env, self.log, self.stub = commands, env, log, stub
        self.script = script

    def check(self, user="user"):
        return subprocess.run(
            [shutil.which("bash"), str(self.script), "--check", user],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.mark.parametrize("tools", ["shadow", "sysusers"])
def test_preflight_supports_both_account_toolsets_without_changes(host, tools):
    names = ("getent", "groupadd", "usermod") if tools == "shadow" else ("systemd-sysusers",)
    for name in names:
        host.stub(name)
    result = host.check()
    assert result.returncode == 0, result.stderr
    assert f"account tools: {tools}" in result.stdout
    called = host.log.read_text().splitlines()
    # command -v probes are fine; no external mutating command may run in --check.
    assert not set(called) & {
        "systemd-sysusers",
        "groupadd",
        "usermod",
        "modprobe",
        "install",
        "udevadm",
    }


def test_missing_account_tools_fails_before_changes(host):
    result = host.check()
    assert result.returncode == 1
    assert "systemd-sysusers" in result.stderr
    assert "install" not in host.log.read_text().splitlines()


def test_sysusers_account_name_cannot_inject_inline_config(host):
    host.stub("systemd-sysusers")
    result = host.check("name with spaces")
    assert result.returncode == 1
    assert "manual group setup" in result.stderr
    assert "systemd-sysusers" not in host.log.read_text().splitlines()


def test_preflight_requires_systemd_tools_not_a_distribution_identity(host):
    host.stub("systemd-sysusers")
    (host.commands / "systemctl").unlink()
    result = host.check()
    assert result.returncode == 1
    assert "systemctl" in result.stderr


def test_built_in_uinput_does_not_require_modprobe(host):
    host.stub("systemd-sysusers")
    # /dev/null is an existing character device on Linux and macOS. Repoint only
    # the test copy's read-only device-presence check; no kernel operations run.
    host.script.write_text(host.script.read_text().replace("/dev/uinput", "/dev/null"))
    (host.commands / "modprobe").unlink()
    result = host.check()
    assert result.returncode == 0, result.stderr
    assert "modprobe" not in host.log.read_text().splitlines()


def test_incomplete_project_fails_before_changing_anything(host):
    (host.script.parent / "70-open-shinkansen.rules").unlink()
    result = host.check()
    assert result.returncode == 1
    assert "Missing setup asset" in result.stderr


@pytest.mark.parametrize(
    "name", ["70-taito-train-controller.rules", "70-train-controller-uinput.rules"]
)
def test_legacy_rules_require_manual_migration_without_removing_them(host, name):
    host.stub("systemd-sysusers")
    legacy = host.commands.parent / "etc" / "rules" / name
    legacy.parent.mkdir(parents=True)
    legacy.write_text("preserve administrator configuration\n")
    result = host.check()
    assert result.returncode == 1
    assert "Legacy permission rules require migration" in result.stderr
    assert legacy.read_text() == "preserve administrator configuration\n"
    assert not set(host.log.read_text().splitlines()) & {"install", "systemd-sysusers", "udevadm"}


def test_rule_permissions_do_not_depend_on_logind_or_grant_all_input_access():
    rules = (ROOT / "linux" / "70-open-shinkansen.rules").read_text()
    active = [line for line in rules.splitlines() if line and not line.startswith("#")]
    assert len(active) == 2
    assert all('GROUP="open-shinkansen"' in line and 'MODE="0660"' in line for line in active)
    assert 'ATTR{idVendor}=="0ae4"' in active[0]
    assert 'ATTR{idProduct}=="0005"' in active[0]
    assert 'ATTRS{name}=="open-shinkansen Virtual Joystick"' in active[1]
    assert "uaccess" not in rules
    assert "0666" not in rules
