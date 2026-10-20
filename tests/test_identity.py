from importlib import metadata
from pathlib import Path

from open_shinkansen import doctor, output, service
from open_shinkansen.daemon import InstanceLock
from open_shinkansen.debug import DebugState, render


def test_distribution_and_executable_use_the_new_project_name():
    package = metadata.distribution("open-shinkansen")
    assert package.metadata["Name"] == "open-shinkansen"
    scripts = {
        entry.name: entry.value
        for entry in package.entry_points
        if entry.group == "console_scripts"
    }
    assert scripts == {"open-shinkansen": "open_shinkansen.cli:main"}


def test_service_and_runtime_identity_are_consistent(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/example")
    assert service.UNIT_NAME == "open-shinkansen.service"
    assert service.MARKER == "# Managed by open-shinkansen service install\n"
    unit = service.render_unit("/home/user/open-shinkansen/.venv/bin/python")
    assert "-m open_shinkansen daemon" in unit
    assert "Description=open-shinkansen" in unit
    assert InstanceLock().directory == Path("/run/user/example/open-shinkansen")


def test_permissions_virtual_device_and_dashboard_share_the_brand():
    root = Path(__file__).parents[1]
    assert doctor.GROUP == "open-shinkansen"
    assert doctor.RULES == ("70-open-shinkansen.rules", "70-open-shinkansen-uinput.rules")
    assert all((root / "linux" / name).is_file() for name in doctor.RULES)
    assert output.DEVICE_NAME == "open-shinkansen Virtual Joystick"
    assert "OPEN-SHINKANSEN / TAITO TCPP-20011" in render(DebugState(), 0)
    assert not (root / "src" / "train_controller").exists()
