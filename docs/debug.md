# Terminal ASCII controller test

`debug` is a standalone, input-only dashboard for **macOS and Linux**. It reads
the physical controller directly using the existing USB driver. It does **not**
create virtual devices, inject keys, or send speedometer/LED/rumble commands.
There are no new UI dependencies: the renderer uses the Python standard library.

## Start on this Mac

Install once using `./setup.sh` from the cloned project. On macOS it needs no
administrator access and creates no Linux background service.

With the controller connected and the project venv installed:

```sh
cd ~/Projects/open-shinkansen
.venv/bin/open-shinkansen debug
```

Run this in your terminal, not through `doctor` or the Linux service installer.
No Linux setup/udev/uinput configuration is needed on macOS. USB access is
exclusive: stop another `monitor`, `debug`, `daemon`, or native USB controller
plugin before starting. On Linux, stop the background service first:

```sh
.venv/bin/open-shinkansen service stop
# Run debug, quit it, then restore automatic operation:
.venv/bin/open-shinkansen service start
```

## What you see

- **Power**: N/P1-P13, a 13-step ASCII bar, raw notch code, and observed positions.
- **Brake**: REL/B1-B7/EB, an eight-step bar including emergency, raw code and
  observed positions. This is physical handle position, not the virtual-axis scale.
- **Buttons**: A/B/C/D/Select/Start live indicators and observed press-edge counts.
- **Pedal**: pressed/released, plus whether both states have been observed.
- **D-pad**: direction label, an ASCII cross highlighting active directions, and
  observed hat positions including diagonals and center.
- **Diagnostics**: raw report bytes, report/change counts, lever-transition and
  unknown-report counts, elapsed time and age of the last report.

Legend: `*` active; `+` observed this run; `.` inactive/unseen; `?` not known yet.
Power coverage uses `N`/`01`-`13`; brake coverage uses `R`/`01`-`07`/`EB`.
Hat coverage uses `U UR R DR D DL L UL C` (C = centered).

An observed code is **not a calibration pass**: compare the on-screen label with
the handle's actual marked position. Button coverage records whether each button
was pressed; it does not certify correct labels, release behavior or contact quality.
Press counts include a button already held when the first valid report arrives,
and are not debounced: contact bounce can produce extra edges.

## Suggested test

1. Start with power N and brake released; check the displayed positions.
2. Slowly sweep P1-P13 and return to N; power coverage should reach **14/14**.
3. Sweep B1-B7 and EB, then release; brake coverage should reach **9/9**.
4. Press and release A/B/C/D/Select/Start; watch the indicators and counts.
5. Test each cardinal D-pad direction, diagonals and centered position.
6. Press/release the horn pedal; both pedal states should be marked observed.
7. Quit with **Ctrl-C**. The original screen/cursor is restored and a summary
   prints in the normal terminal.

The dashboard refreshes at up to **10 frames/second**, but processes every USB
report received. Very brief presses may be easier to see in the persistent press
counts and coverage markers than in the momentary active indicator. Resize the
terminal for a full **80x24** view; a compact layout works down to **40x13**.
Smaller windows display a resize hint.

Idle timeouts are normal because the controller need not send heartbeat packets.
An old report age is not proof of disconnection. Lever `ff` transition codes hold
the last valid position and do not increase coverage. Unknown codes, including
the observed zero-valued startup report, are counted separately and never rounded
to a notch. Unknown counts are diagnostic, **not automatic test failures**.

## Record, replay, or use plain output

```sh
# Stop automatically after 90 seconds and save the raw reports:
.venv/bin/open-shinkansen debug --duration 90 --record captures/debug-session.jsonl

# Replay without opening USB (no controller required):
.venv/bin/open-shinkansen debug --replay tests/fixtures/demo.jsonl
.venv/bin/open-shinkansen debug --replay captures/debug-session.jsonl

# Plain ASCII snapshots, without cursor/screen control sequences:
.venv/bin/open-shinkansen debug --plain
```

Capture files must not already exist; they are never truncated. Replay uses the
capture's timing and exits at EOF. Counters reset with each new command. All exits
including USB errors, Ctrl-C and SIGTERM unwind the terminal/USB resources. USB
errors end `debug`; it is not the automatically reconnecting `daemon` command.

A real terminal uses its alternate screen and hides the cursor only for this
command. Output redirected to a file/pipe, `TERM=dumb`, or `--plain` uses plain
snapshots instead. Those snapshots are rate-limited and emitted for new reports,
plus an initial/final frame; they do not continuously spam idle status updates.
The UI does not read ordinary keyboard input; Ctrl-C is the quit action.
