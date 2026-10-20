from pathlib import Path
from unittest.mock import MagicMock

import pytest

from open_shinkansen import service


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(service.sys, "platform", "linux")
    monkeypatch.setattr(service.os, "geteuid", lambda: 1000)
    # A venv path must be kept verbatim, not realpath-resolved to system Python.
    monkeypatch.setattr(
        service.sys, "executable", "/home/player/test directory/open-shinkansen/.venv/bin/python"
    )
    run = MagicMock()
    monkeypatch.setattr(service.subprocess, "run", run)
    return run


def test_install_enables_user_unit_no_sudo_and_no_keyboard(environment):
    service.manage("install")
    path = service.unit_path()
    content = path.read_text()
    assert (
        'ExecStart="/home/player/test directory/open-shinkansen/.venv/bin/python" -m open_shinkansen daemon'
        in content
    )
    assert "WantedBy=default.target" in content
    assert "NoNewPrivileges=yes" in content
    assert "Restart=on-failure" in content
    assert "RestartSec=10" in content
    assert "keyboard" not in content
    assert "User=root" not in content
    assert "PrivateDevices=yes" not in content
    # The worker owns its runtime lock directory. A failed unit start must not
    # delete a foreground worker's live lock and permit a second daemon.
    assert "RuntimeDirectory=" not in content
    assert [call.args[0] for call in environment.call_args_list] == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", service.UNIT_NAME],
    ]


def test_identical_install_is_idempotent(environment):
    service.manage("install")
    content = service.unit_path().read_text()
    service.manage("install")
    assert service.unit_path().read_text() == content
    assert not list(service.unit_path().parent.glob("*.backup-*"))


def test_service_can_be_enabled_without_starting_before_reboot(environment):
    service.manage("install", start=False)
    assert service.unit_path().exists()
    assert [call.args[0] for call in environment.call_args_list] == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", service.UNIT_NAME],
    ]


def test_existing_custom_unit_is_not_overwritten_without_explicit_replace(environment):
    path = service.unit_path()
    path.parent.mkdir(parents=True)
    path.write_text("my existing unit")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        service.manage("install")
    assert path.read_text() == "my existing unit"
    environment.assert_not_called()
    service.manage("install", replace=True)
    backups = list(path.parent.glob("*.backup-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "my existing unit"
    assert path.read_text().startswith(service.MARKER)


def test_uninstall_preserves_unfamiliar_units(environment):
    path = service.unit_path()
    path.parent.mkdir(parents=True)
    path.write_text("not managed here")
    with pytest.raises(RuntimeError, match="unfamiliar"):
        service.manage("uninstall")
    assert path.exists()
    environment.assert_not_called()


def test_uninstall_stops_unit_and_removes_only_managed_file(environment):
    service.manage("install")
    environment.reset_mock()
    service.manage("uninstall")
    assert not service.unit_path().exists()
    assert [call.args[0] for call in environment.call_args_list] == [
        ["systemctl", "--user", "disable", "--now", service.UNIT_NAME],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_root_and_non_linux_service_install_refused(environment, monkeypatch):
    monkeypatch.setattr(service.os, "geteuid", lambda: 0)
    with pytest.raises(RuntimeError, match="NOT sudo"):
        service.manage("install")
    monkeypatch.setattr(service.sys, "platform", "darwin")
    with pytest.raises(RuntimeError, match="Linux"):
        service.manage("install")
    environment.assert_not_called()


def test_unit_escape_percent_dollar_quotes_and_backslash():
    content = service.render_unit('/home/a%/$b/space " \\ /python')
    assert 'a%%/$$b/space \\" \\\\ /python' in content
    with pytest.raises(ValueError):
        service.render_unit("relative/python")
    with pytest.raises(ValueError):
        service.render_unit("/home/a\ninjected/python")


def test_unit_symlink_is_never_replaced(environment, tmp_path):
    path = service.unit_path()
    path.parent.mkdir(parents=True)
    target = tmp_path / "important"
    target.write_text("preserve")
    path.symlink_to(target)
    with pytest.raises(RuntimeError, match="symlink"):
        service.manage("install", replace=True)
    assert target.read_text() == "preserve"
    environment.assert_not_called()


@pytest.mark.parametrize("action", ["start", "stop", "restart", "status"])
def test_controls_use_only_user_manager(environment, action):
    service.manage(action)
    environment.assert_called_once_with(
        ["systemctl", "--user", action, service.UNIT_NAME], check=True
    )


def test_log_command_is_read_only_and_bounded(environment):
    service.manage("logs")
    environment.assert_called_once_with(
        ["journalctl", "--user", "-u", service.UNIT_NAME, "-n", "80", "--no-pager"], check=True
    )


def test_example_host_module_only_loads_uinput():
    config = Path(__file__).parents[1] / "linux" / "open-shinkansen.conf"
    modules = [
        line for line in config.read_text().splitlines() if line and not line.startswith("#")
    ]
    assert modules == ["uinput"]
