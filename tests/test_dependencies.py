import sys
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from open_shinkansen.installer import binary_evdev


@pytest.mark.parametrize("system", ["linux", "darwin", "win32"])
@pytest.mark.parametrize("machine", ["x86_64", "aarch64"])
@pytest.mark.parametrize("implementation", ["cpython", "pypy"])
@pytest.mark.parametrize("version", [(3, 9), (3, 13), (3, 14), (3, 15)])
def test_exactly_one_input_provider_is_selected_for_linux(system, machine, implementation, version):
    project = Path(__file__).parents[1] / "pyproject.toml"
    with project.open("rb") as handle:
        requirements = tomllib.load(handle)["project"]["dependencies"]
    env = {
        **default_environment(),
        "sys_platform": system,
        "platform_machine": machine,
        "implementation_name": implementation,
        "python_version": ".".join(map(str, version)),
    }
    selected = [
        requirement.name
        for text in requirements
        for requirement in [Requirement(text)]
        if requirement.name in {"evdev", "evdev-binary"} and requirement.marker.evaluate(env)
    ]
    expected = (
        []
        if system != "linux"
        else ["evdev-binary" if binary_evdev(system, machine, implementation, version) else "evdev"]
    )
    assert selected == expected


@pytest.mark.skipif(sys.platform != "linux", reason="Real input-module import requires Linux")
def test_actual_linux_input_provider_exports_the_required_api_without_creating_a_device():
    from evdev import AbsInfo, UInput, ecodes

    from open_shinkansen.profiles import KEY_NAMES

    assert AbsInfo(0, 0, 32767, 0, 0, 0).max == 32767
    assert callable(UInput)
    for name in (
        *KEY_NAMES,
        "BUS_VIRTUAL",
        "BTN_JOYSTICK",
        "ABS_X",
        "ABS_Y",
        "ABS_HAT0X",
        "ABS_HAT0Y",
        "EV_KEY",
        "EV_ABS",
    ):
        assert isinstance(getattr(ecodes, name), int)
