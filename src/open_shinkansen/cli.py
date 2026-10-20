import argparse
import json
import logging
import math
import signal
import sys
import threading
import time
from contextlib import ExitStack

from . import __version__
from .events import JoystickMapper, KeyboardMapper
from .output import DryRun, UInputOutput
from .profiles import load
from .protocol import Display, decode
from .stream import recorder, samples


def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return result


def parser():
    root = argparse.ArgumentParser(
        description="open-shinkansen: Taito TCPP-20011 USB driver and Linux bridge"
    )
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("discover", help="Open the controller and print its USB descriptors")
    doctor = sub.add_parser(
        "doctor", help="Read-only Linux/systemd setup checks (no controller required)"
    )
    doctor.add_argument("--json", action="store_true", help="Print machine-readable setup results")
    daemon = sub.add_parser("daemon", help="Joystick-only hotplug background worker")
    daemon.add_argument(
        "--poll-interval",
        type=positive,
        default=1.0,
        help="Seconds between USB reconnect attempts (0.1..60; default 1)",
    )
    daemon.add_argument("--dry-run", action="store_true", help="Print events; do not inject input")
    daemon.add_argument(
        "--duration", type=positive, help="Stop after this many seconds (diagnostics)"
    )
    service = sub.add_parser("service", help="Manage the current user's Linux systemd service")
    actions = service.add_subparsers(dest="action", required=True)
    install = actions.add_parser("install", help="Enable automatic startup at user login")
    install.add_argument(
        "--replace", action="store_true", help="Back up and replace a differing unit"
    )
    for action in ("uninstall", "start", "stop", "restart", "status", "logs"):
        actions.add_parser(action)
    monitor = sub.add_parser("monitor", help="Watch decoded inputs (macOS or Linux)")
    monitor.add_argument("--json", action="store_true", help="Emit decoded state as JSONL")
    monitor.add_argument(
        "--all", action="store_true", help="Show every report, including transitions"
    )
    debug = sub.add_parser(
        "debug", help="Live ASCII input dashboard (macOS or Linux; no injection)"
    )
    debug.add_argument(
        "--plain", action="store_true", help="Print snapshots instead of a live terminal screen"
    )
    bridge = sub.add_parser("bridge", help="Translate inputs into a virtual Linux device")
    bridge.add_argument("--output", choices=("joystick", "keyboard"), default="joystick")
    bridge.add_argument("--profile", help="Keyboard mapping JSON; required for keyboard output")
    bridge.add_argument("--dry-run", action="store_true", help="Print events; do not inject input")
    for command in (monitor, bridge, debug):
        command.add_argument(
            "--replay", metavar="FILE", help="Read timed JSONL instead of real USB"
        )
        command.add_argument("--record", metavar="FILE", help="Save raw JSONL; file must not exist")
        command.add_argument("--duration", type=positive, help="Stop after this many seconds")
    display = sub.add_parser("display", help="Temporarily set LEDs (no rumble), then clear them")
    display.add_argument("--speed", type=int, default=0, help="0..999 km/h")
    display.add_argument("--limit", type=int, default=0, help="0..999 km/h")
    display.add_argument("--door", action="store_true")
    display.add_argument("--approach", type=int, default=0, help="0..10 LEDs")
    display.add_argument("--gauge", type=int, help="0..22 LEDs (default: calculated from speed)")
    display.add_argument(
        "--hold", type=positive, default=3, help="Seconds before clearing (default 3)"
    )
    return root


def _run_inputs(args):
    profile = None
    if args.command == "bridge" and args.output == "keyboard":
        if not args.profile:
            raise ValueError("Keyboard output requires --profile; see profiles/ for templates")
        profile = load(args.profile)
    elif args.command == "bridge" and args.profile:
        raise ValueError("--profile is only used with --output keyboard")
    mapper = None
    output = None
    with ExitStack() as stack:
        # Validate/create the capture before claiming USB. All resources unwind on error.
        record = stack.enter_context(recorder(args.record))
        if args.replay:
            source = samples(replay=args.replay, duration=args.duration)
        else:
            from .usb import Controller

            controller = stack.enter_context(Controller())
            source = samples(read=lambda: controller.read(20), duration=args.duration)
            print("Connected to TCPP-20011. Ctrl-C to stop.", file=sys.stderr)
        if args.command == "bridge":
            mapper = KeyboardMapper(profile) if profile else JoystickMapper()
            output = DryRun() if args.dry_run else UInputOutput(args.output)
            stack.callback(output.close)
            stack.callback(lambda: output.emit(mapper.close()))
            if profile:
                print(
                    "Keyboard mapping active. Relative axes use the first physical position as "
                    "the game baseline; synchronize the game first. Keys go to the focused app.",
                    file=sys.stderr,
                )
        previous = None
        for at, raw in source:
            if raw is not None:
                record(at, raw)
                state = decode(raw, previous)
                if mapper:
                    mapped = mapper.update(state)
                    if mapped is not None:
                        output.emit(mapped)
                elif args.all or state != previous:
                    if args.json:
                        print(
                            json.dumps({"t": round(at, 6), "raw": raw.hex(" "), **state.to_dict()}),
                            flush=True,
                        )
                    else:
                        power = "?" if state.power is None else f"P{state.power}"
                        brake = (
                            "EB"
                            if state.emergency
                            else ("?" if state.brake is None else f"B{state.brake}")
                        )
                        buttons = ",".join(sorted(state.buttons)) or "-"
                        print(
                            f"{at:8.3f}s  power={power:>3} brake={brake:>2} "
                            f"pedal={int(state.pedal)} hat={state.hat} "
                            f"buttons={buttons}  [{raw.hex(' ')}]",
                            flush=True,
                        )
                previous = state
            if isinstance(mapper, KeyboardMapper):
                output.emit(mapper.tick(time.monotonic()))


def _run_debug(args):
    from .debug import Dashboard, DebugState, summary

    with ExitStack() as stack:
        record = stack.enter_context(recorder(args.record))
        if args.replay:
            source = samples(replay=args.replay, duration=args.duration)
            label = "REPLAY FILE (no USB access)"
        else:
            from .usb import Controller

            controller = stack.enter_context(Controller())
            source = samples(read=lambda: controller.read(20), duration=args.duration)
            label = "LIVE USB 0ae4:0005"
        model = DebugState()
        # Register before the screen so the final summary prints after restoring
        # the original terminal, including when Ctrl-C or a USB error ends the run.
        stack.callback(lambda: print(summary(model), flush=True))
        dashboard = stack.enter_context(Dashboard(label, bool(args.record), args.plain))
        elapsed = 0.0
        dashboard.draw(model, elapsed, force=True)
        try:
            for elapsed, raw in source:
                if raw is not None:
                    record(elapsed, raw)
                    model.observe(elapsed, raw)
                dashboard.draw(model, elapsed)
        finally:
            dashboard.draw(model, elapsed, force=True)


def _run(args):
    if args.command == "debug":
        _run_debug(args)
        return
    if args.command == "doctor":
        from .doctor import inspect

        report = inspect()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            for check in report["checks"]:
                print(f"{'OK' if check['ok'] else 'FAIL'} {check['name']}: {check['detail']}")
            print(
                "Checks passed; verify real joystick/game behavior separately."
                if report["ready"]
                else "Initial setup incomplete; see docs/linux-setup.md."
            )
        return 0 if report["ready"] else 1
    if args.command == "service":
        from .service import manage

        manage(args.action, replace=getattr(args, "replace", False))
        return
    if args.command in ("monitor", "bridge"):
        _run_inputs(args)
        return
    from .usb import Controller

    if args.command == "discover":
        with Controller() as controller:
            print(json.dumps(controller.describe(), indent=2))
    else:
        display = Display(args.speed, args.limit, args.door, args.approach, args.gauge)
        display.encode()  # Validate before USB access.
        with Controller() as controller:
            try:
                controller.write_display(display)
                print(f"Display set for {args.hold:g}s; rumble motors OFF.", flush=True)
                time.sleep(args.hold)
            finally:
                controller.write_display(Display())


def main(argv=None):
    args = parser().parse_args(argv)

    stop = threading.Event()

    def terminate(signum, frame):
        if args.command == "daemon":
            stop.set()
        else:
            raise KeyboardInterrupt

    old_term = signal.signal(signal.SIGTERM, terminate)
    old_int = signal.signal(signal.SIGINT, terminate) if args.command == "daemon" else None
    try:
        if args.command == "daemon":
            from .daemon import InstanceLock, run

            if not args.dry_run and sys.platform != "linux":
                raise RuntimeError("Daemon injection requires Linux. Use --dry-run on macOS.")
            logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
            timer = threading.Timer(args.duration, stop.set) if args.duration else None
            try:
                if timer:
                    timer.daemon = True
                    timer.start()
                with InstanceLock():
                    run(
                        stop,
                        poll_interval=args.poll_interval,
                        output_factory=DryRun if args.dry_run else None,
                    )
            finally:
                if timer:
                    timer.cancel()
        else:
            result = _run(args)
            if result is not None:
                return result
        return 0
    except KeyboardInterrupt:
        print(
            "Debug stopped; USB closed, no input injected."
            if args.command == "debug"
            else "Stopped; virtual inputs released.",
            file=sys.stderr,
        )
        return 130
    except BrokenPipeError:
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if isinstance(exc, PermissionError) or getattr(exc, "errno", None) == 13:
            print(
                "See docs/linux-setup.md for USB/uinput permissions. Do not run the bridge "
                "as root for normal use.",
                file=sys.stderr,
            )
        return 1
    finally:
        signal.signal(signal.SIGTERM, old_term)
        if old_int is not None:
            signal.signal(signal.SIGINT, old_int)
