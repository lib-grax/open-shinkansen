import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from open_shinkansen import doctor, installer, service


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project with spaces"
    (root / "linux").mkdir(parents=True)
    (root / "linux/setup-permissions.sh").write_text("# fake helper\n")
    (root / "pyproject.toml").write_text("# fake project\n")
    return root


def arguments(**kwargs):
    return SimpleNamespace(**{"dev": False, "replace_service": False, **kwargs})


def user():
    return SimpleNamespace(pw_name="controller-user", pw_gid=1000)


def test_bootstrap_creates_private_environment_and_reexecutes_only_its_python(project, monkeypatch):
    monkeypatch.setattr(installer, "preflight", MagicMock())
    monkeypatch.setattr(installer, "usable_venv", lambda directory: False)
    builder = MagicMock()
    monkeypatch.setattr(installer.venv, "EnvBuilder", builder)
    run = MagicMock()
    monkeypatch.setattr(installer, "run", run)
    installer.bootstrap(project, arguments(), user())
    builder.assert_called_once_with(with_pip=True)
    builder.return_value.create.assert_called_once_with(project / ".venv")
    command = run.call_args.args[0]
    assert command[0] == project / ".venv/bin/python"
    assert command[-1] == "--_venv"


def test_unusable_environment_is_backed_up_not_deleted(project, monkeypatch):
    monkeypatch.setattr(installer, "preflight", MagicMock())
    monkeypatch.setattr(installer, "usable_venv", lambda directory: False)
    monkeypatch.setattr(installer, "run", MagicMock())
    monkeypatch.setattr(installer.venv, "EnvBuilder", MagicMock())
    old = project / ".venv"
    old.mkdir()
    (old / "preserve.txt").write_text("user environment data")
    installer.bootstrap(project, arguments(), user())
    backups = list(project.glob(".venv-backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "preserve.txt").read_text() == "user environment data"


def test_symlink_environment_is_never_modified(project, monkeypatch):
    monkeypatch.setattr(installer, "preflight", MagicMock())
    target = project / "other-environment"
    target.mkdir()
    (project / ".venv").symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        installer.bootstrap(project, arguments(), user())
    assert target.is_dir()


def test_child_failure_is_returned_without_hiding_its_error(project, monkeypatch):
    monkeypatch.setattr(installer, "preflight", MagicMock())
    monkeypatch.setattr(installer, "usable_venv", lambda directory: True)
    monkeypatch.setattr(
        installer, "run", MagicMock(side_effect=subprocess.CalledProcessError(7, ["python"]))
    )
    assert installer.bootstrap(project, arguments(), user()) == 7


def test_environment_probe_checks_prefix_platform_version_and_pip(project, monkeypatch):
    directory = project / ".venv"
    (directory / "bin").mkdir(parents=True)
    (directory / "bin/python").touch()
    run = MagicMock(
        return_value=SimpleNamespace(
            returncode=0,
            stdout=json.dumps([str(directory), "/system/python", installer.sys.platform, [3, 13]]),
        )
    )
    monkeypatch.setattr(installer.subprocess, "run", run)
    assert installer.usable_venv(directory)
    assert "pip" in run.call_args.args[0][-1]
    run.return_value = SimpleNamespace(returncode=1, stdout="")
    assert not installer.usable_venv(directory)
    run.side_effect = OSError("Wrong executable format")
    assert not installer.usable_venv(directory)


def test_preflight_requires_a_reachable_user_manager_before_any_admin_change(project, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.shutil, "which", lambda command: "/usr/bin/" + command)
    monkeypatch.setattr(
        installer.subprocess, "run", MagicMock(return_value=SimpleNamespace(returncode=1))
    )
    run = MagicMock()
    monkeypatch.setattr(installer, "run", run)
    with pytest.raises(RuntimeError, match="user session"):
        installer.preflight(project, user())
    run.assert_not_called()


def test_finish_cannot_run_pip_outside_the_project_environment(project, monkeypatch):
    monkeypatch.setattr(installer.sys, "prefix", "/unrelated/environment")
    run = MagicMock()
    monkeypatch.setattr(installer, "run", run)
    with pytest.raises(RuntimeError, match="outside"):
        installer.finish(project, arguments(), user())
    run.assert_not_called()


@pytest.mark.parametrize("binary,wrong", [(True, "evdev"), (False, "evdev-binary")])
def test_conflicting_input_providers_are_migrated_only_inside_the_venv(monkeypatch, binary, wrong):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer, "binary_evdev", lambda: binary)
    distribution = MagicMock()
    monkeypatch.setattr(installer.metadata, "distribution", distribution)
    run = MagicMock()
    monkeypatch.setattr(installer, "run", run)
    installer.prepare_evdev()
    distribution.assert_called_once_with(wrong)
    assert run.call_args.args[0] == [
        installer.sys.executable,
        "-m",
        "pip",
        "uninstall",
        "--yes",
        "evdev",
        "evdev-binary",
    ]


def test_no_input_provider_is_removed_when_there_is_no_conflict(monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(
        installer.metadata,
        "distribution",
        MagicMock(side_effect=installer.metadata.PackageNotFoundError),
    )
    run = MagicMock()
    monkeypatch.setattr(installer, "run", run)
    installer.prepare_evdev()
    run.assert_not_called()


@pytest.fixture
def installed(project, monkeypatch):
    monkeypatch.setattr(installer.sys, "prefix", str(project / ".venv"))
    monkeypatch.setattr(installer.sys, "base_prefix", "/system/python")
    monkeypatch.setattr(installer.sys, "executable", str(project / ".venv/bin/python"))
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer, "prepare_evdev", MagicMock())
    monkeypatch.setattr(installer.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(installer, "administrator_command", lambda: "/usr/bin/sudo")
    monkeypatch.setattr(installer, "permissions_configured", lambda *args: False)
    monkeypatch.setitem(
        installer.sys.modules,
        "evdev",
        SimpleNamespace(
            AbsInfo=object, UInput=object, ecodes=SimpleNamespace(EV_KEY=1, BTN_JOYSTICK=288)
        ),
    )
    device = MagicMock()
    device.is_char_device.return_value = True
    monkeypatch.setattr(doctor, "UINPUT", device)
    run = MagicMock()
    install, manage = MagicMock(), MagicMock()
    monkeypatch.setattr(installer, "run", run)
    monkeypatch.setattr(service, "install", install)
    monkeypatch.setattr(service, "manage", manage)
    return run, install, manage


def report(failed=()):
    return {
        "checks": [
            {"name": name, "ok": name not in failed, "detail": name}
            for name in (
                "linux",
                "python",
                "evdev",
                "permission_group",
                "uinput_access",
                "permission_rules",
            )
        ]
    }


def test_new_group_enables_service_then_requests_reboot_without_starting_it(
    project, installed, monkeypatch, capsys
):
    run, install, manage = installed
    monkeypatch.setattr(doctor, "group_active", lambda: False)
    monkeypatch.setattr(doctor, "inspect", lambda: report({"permission_group", "uinput_access"}))
    installer.finish(project, arguments(), user())
    install.assert_called_once_with(replace=False, start=False)
    manage.assert_called_once_with("stop")
    assert "REBOOT REQUIRED" in capsys.readouterr().out
    commands = [call.args[0] for call in run.call_args_list]
    assert commands[0][0] == str(project / ".venv/bin/python")
    assert commands[1][-1] == str(project)
    assert commands[2] == [
        "/usr/bin/sudo",
        "bash",
        project / "linux/setup-permissions.sh",
        "controller-user",
    ]
    assert all("reboot" not in command and "shutdown" not in command for command in commands)


def test_ready_host_starts_service_without_requesting_reboot(
    project, installed, monkeypatch, capsys
):
    run, install, manage = installed
    monkeypatch.setattr(doctor, "group_active", lambda: True)
    monkeypatch.setattr(doctor, "inspect", lambda: report())
    installer.finish(project, arguments(), user())
    install.assert_called_once_with(replace=False, start=False)
    manage.assert_called_once_with("restart")
    assert "enabled and running" in capsys.readouterr().out
    assert run.call_args.args[0] == ["systemctl", "--user", "is-active", "--quiet", installer.UNIT]


def test_rerun_with_matching_permissions_does_not_request_admin_access(
    project, installed, monkeypatch
):
    run, install, manage = installed
    monkeypatch.setattr(installer, "permissions_configured", lambda *args: True)
    monkeypatch.setattr(doctor, "group_active", lambda: True)
    monkeypatch.setattr(doctor, "inspect", lambda: report())
    installer.finish(project, arguments(), user())
    assert all(call.args[0][0] != "/usr/bin/sudo" for call in run.call_args_list)


def test_unexpected_permission_failure_does_not_enable_a_broken_service(
    project, installed, monkeypatch
):
    run, install, manage = installed
    monkeypatch.setattr(doctor, "group_active", lambda: True)
    monkeypatch.setattr(doctor, "inspect", lambda: report({"uinput_access"}))
    with pytest.raises(RuntimeError, match="Host setup checks failed"):
        installer.finish(project, arguments(), user())
    install.assert_not_called()
    manage.assert_not_called()


def test_macos_setup_installs_only_usb_tools_without_sudo_or_systemd(
    project, installed, monkeypatch, capsys
):
    run, install, manage = installed
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    installer.finish(project, arguments(), user())
    install.assert_not_called()
    manage.assert_not_called()
    assert len(run.call_args_list) == 2
    assert "macOS USB/debug tools" in capsys.readouterr().out


def test_setup_refuses_root_and_does_not_change_anything(monkeypatch, capsys):
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    bootstrap = MagicMock()
    monkeypatch.setattr(installer, "bootstrap", bootstrap)
    assert installer.main([]) == 1
    assert "Do not run" in capsys.readouterr().err
    bootstrap.assert_not_called()


def test_setup_help_works_from_outside_the_checkout_without_changes(tmp_path):
    root = Path(__file__).parents[1]
    result = subprocess.run(
        ["bash", str(root / "setup.sh"), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "one-time open-shinkansen setup" in result.stdout.lower()


def test_existing_permission_configuration_is_verified_without_overwriting_it(
    project, tmp_path, monkeypatch
):
    target = tmp_path / "host-config"
    target.mkdir()
    names = ("controller.rules", "uinput.rules", "module.conf")
    monkeypatch.setattr(installer, "ASSETS", tuple((name, str(target)) for name in names))
    for name in names:
        (project / "linux" / name).write_text(name)
        (target / name).write_text(name)
    group = SimpleNamespace(gr_gid=1234, gr_mem=["controller-user"])
    monkeypatch.setattr(installer.grp, "getgrnam", lambda name: group)
    monkeypatch.setattr(installer.os, "getgroups", lambda: [1000])
    monkeypatch.setattr(installer.os, "getegid", lambda: 1000)
    device = MagicMock()
    device.is_char_device.return_value = True
    monkeypatch.setattr(installer, "UINPUT", device)
    monkeypatch.setattr(installer.os, "access", lambda *args: False)
    # Persistent membership already exists; current-session permissions can wait for reboot.
    assert installer.permissions_configured(project, user())
    monkeypatch.setattr(installer.os, "getgroups", lambda: [1000, 1234])
    assert not installer.permissions_configured(
        project, user()
    )  # Active group but access denied: reapply rules.
    monkeypatch.setattr(installer.os, "access", lambda *args: True)
    assert installer.permissions_configured(project, user())
    (target / names[0]).write_text("administrator edits")
    assert not installer.permissions_configured(project, user())
    assert (target / names[0]).read_text() == "administrator edits"
