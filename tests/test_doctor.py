import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from open_shinkansen import doctor, usb
from open_shinkansen.cli import main


@pytest.fixture
def ready_host(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    monkeypatch.setattr(doctor.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/" + name)
    manager = MagicMock(return_value=SimpleNamespace(returncode=0, stdout=b"SECRET=never_print\n"))
    monkeypatch.setattr(doctor.subprocess, "run", manager)
    monkeypatch.setattr(usb, "backend", lambda: object())
    monkeypatch.setattr(doctor, "group_active", lambda: True)
    device = MagicMock()
    device.is_char_device.return_value = True
    monkeypatch.setattr(doctor, "UINPUT", device)
    monkeypatch.setattr(doctor.os, "access", lambda *args: True)
    monkeypatch.setattr(doctor, "RULES_DIRECTORY", tmp_path)
    for name in doctor.RULES:
        (tmp_path / name).write_text("test rule\n")
    return manager


def checks(report):
    return {check["name"]: check["ok"] for check in report["checks"]}


def test_capability_check_is_distribution_agnostic_and_does_not_open_usb(ready_host, monkeypatch):
    controller = MagicMock(side_effect=AssertionError("Must not claim USB"))
    monkeypatch.setattr(usb, "Controller", controller)
    report = doctor.inspect()
    assert report["ready"]
    assert all(checks(report).values())
    assert "SECRET" not in json.dumps(report)
    assert "Steam" not in json.dumps(report)
    controller.assert_not_called()
    ready_host.assert_called_once_with(
        ["systemctl", "--user", "show-environment"],
        capture_output=True,
        timeout=5,
        check=False,
    )


def test_no_systemctl_reports_missing_user_manager_without_running_any_command(
    ready_host, monkeypatch
):
    monkeypatch.setattr(
        doctor.shutil, "which", lambda name: None if name == "systemctl" else "/bin/" + name
    )
    report = doctor.inspect()
    assert not report["ready"]
    assert not checks(report)["systemd_user"]
    ready_host.assert_not_called()


@pytest.mark.parametrize("error", [OSError("No bus"), subprocess.TimeoutExpired("systemctl", 5)])
def test_unreachable_user_manager_is_a_check_failure(ready_host, error):
    ready_host.side_effect = error
    report = doctor.inspect()
    assert not report["ready"]
    assert not checks(report)["systemd_user"]


def test_missing_permissions_are_actionable_not_root_fallback(ready_host, monkeypatch):
    monkeypatch.setattr(doctor.os, "access", lambda *args: False)
    monkeypatch.setattr(doctor, "group_active", lambda: False)
    report = doctor.inspect()
    assert not report["ready"]
    assert not checks(report)["uinput_access"]
    assert not checks(report)["permission_group"]


def test_non_linux_root_or_missing_modules_fail_checks(ready_host, monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    monkeypatch.setattr(doctor.os, "geteuid", lambda: 0)
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda name: None)
    report = doctor.inspect()
    assert not report["ready"]
    for name in ("linux", "normal_user", "usb", "evdev"):
        assert not checks(report)[name]


def test_unavailable_libusb_backend_does_not_abort_other_checks(ready_host, monkeypatch):
    monkeypatch.setattr(usb, "backend", MagicMock(side_effect=usb.DeviceError("Backend missing")))
    report = doctor.inspect()
    assert not report["ready"]
    assert not checks(report)["libusb_backend"]
    assert checks(report)["systemd_user"]


def test_missing_rules_reported(ready_host):
    (doctor.RULES_DIRECTORY / doctor.RULES[0]).unlink()
    assert not checks(doctor.inspect())["permission_rules"]


@pytest.mark.parametrize("ready", [True, False])
def test_cli_json_and_exit_status(ready, monkeypatch, capsys):
    report = {"ready": ready, "checks": [{"name": "test", "ok": ready, "detail": "Example"}]}
    monkeypatch.setattr(doctor, "inspect", lambda: report)
    assert main(["doctor", "--json"]) == (0 if ready else 1)
    assert json.loads(capsys.readouterr().out) == report


def test_group_active_uses_current_process_groups_not_future_membership(monkeypatch):
    import grp

    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=12345))
    monkeypatch.setattr(doctor.os, "getegid", lambda: 1000)
    monkeypatch.setattr(doctor.os, "getgroups", lambda: [1000])
    assert not doctor.group_active()
    monkeypatch.setattr(doctor.os, "getgroups", lambda: [1000, 12345])
    assert doctor.group_active()
    monkeypatch.setattr(grp, "getgrnam", MagicMock(side_effect=KeyError("missing")))
    assert not doctor.group_active()
