# Hardware validation

## Observed on the attached Mac

- Apple Silicon macOS, PyUSB + bundled libusb.
- `0ae4:0005`, product `TAITO_DENSYA_CON_T02`, serial `TCPP20011`.
- USB 1.1 / low speed; one HID-class interface **without** a HID report descriptor.
- Endpoint `0x81`, interrupt IN, maximum packet 8, interval 20ms.
- Successfully claimed the interface without root or a kernel extension.
- Observed six-byte startup report: `00 00 ff 08 00 00` (unknown lever codes).
- Observed six-byte stable report: `fb 12 ff 08 00 00` (EB, N, pedal released,
  centered D-pad, no buttons). No input changes -> read timeouts, which are normal.

## Completed live sweep and display test

The operator exercised the connected controller during a 90-second capture:
`captures/hardware-sweep-01.jsonl` (local/ignored, not the synthetic demo).

- **327 six-byte reports**, 131 containing a lever-transition byte.
- **All 14 power positions** (N, P1–P13) and **all 9 brake positions** (released,
  B1–B7, EB) observed, with exact documented codes.
- **A/B/C/D/Select/Start** each observed active and released.
- **Horn pedal** pressed/released multiple times, with `00`/`ff` encoding.
- D-pad up/right/down/left/center observed. **Diagonals were not captured**;
  their decoding is covered by protocol-reference unit tests, not physical testing.
- Only unknown lever code was `ff` during transitions; no unexpected notch values.
- Final observed state: power N, brake EB, pedal released, no buttons.
- Vendor display write and zero-reset completed successfully. Operator visually
  confirmed speed **120**, ATC **160** and door lamp, then **0 / 0** on reset.
  Gauge LED count was not separately visually verified. Rumble stayed disabled.

**Still unverified:** diagonal D-pad combinations on hardware, Linux uinput,
hot-unplug behavior on real Linux hardware and all in-game integrations.
`tests/fixtures/demo.jsonl` remains synthetic; it is not a hardware log.

## Background worker checks (v0.2.0)

- A bounded three-second `daemon --dry-run` run opened the real USB controller
  on this Mac, emitted the observed N/EB state, then released its generated
  state and exited normally on its diagnostic timer. No real virtual input was
  injected and no display/motor writes were sent.
- Hardware-free tests cover no-device startup, idle timeouts, simulated unplug
  and reconnect, fresh decoding on each attachment, duplicate daemon exclusion,
  fatal uinput setup errors, and SIGTERM/SIGINT cleanup with handler restoration.
- Service generation/management is tested with mocked systemctl calls. No actual
  systemd user service has yet been installed or verified on a real Linux host.

## Interactive capture checklist

Stop any other USB consumer first.

For the visual terminal test on macOS or Linux, use `debug` instead of the line
monitor; it also supports the same raw capture format:

```sh
.venv/bin/open-shinkansen debug --duration 90 --record captures/ascii-sweep.jsonl
```

See [debug.md](debug.md) for the ASCII indicators, coverage and press counts.
Alternatively, use the existing line-by-line monitor:

```sh
.venv/bin/open-shinkansen monitor --all --duration 90 --record captures/hardware-sweep.jsonl
```

During those 90 seconds:

1. Leave power at N and brake at released for a couple of seconds.
2. Move power through P1..P13, pausing at every notch; return to N.
3. Move brake through B1..B7 and EB, pausing at every notch; release.
4. Press/release A, B, C, D, Select and Start individually.
5. Press each D-pad direction and diagonals.
6. If available, connect and press/release the horn pedal.
7. Leave power N and brake released at the end.

Tell the developer which actions you performed and whether a pedal is present.
Use separate captures when notch labels need correlation; transitions should
retain the last valid notch and never jump to full power.

## ASCII dashboard validation

- Synthetic replay and a real pseudo-terminal test cover live-screen rendering,
  small-window behavior, cursor/screen restoration, SIGTERM cleanup and unchanged
  terminal settings. Plain output has no terminal escape sequences.
- The previous 327-report hardware capture was fed through the debug model and
  renderer: power **14/14**, brake **9/9**, buttons **6/6**, pedal **2/2**, and hat
  **5/9** (the four cardinal directions and center, matching that capture).
- A bounded live `debug --plain` run claimed the real controller on this Mac and
  shut down cleanly. No new reports arrived while idle; move a handle to begin
  live input observation. No display/rumble commands or input injection were used.
- Visual confirmation in the operator's own terminal is still separate from the
  renderer/replay tests; run `open-shinkansen debug` for that interactive test.

## Display verification (with operator permission)

Run `open-shinkansen display --speed 120 --limit 160 --door --hold 3`.
Confirm 120 speed, 160 ATC, eight gauge LEDs and door lamp, then clearing after
three seconds. Motors must remain off. This is manual test data, not telemetry.

## Linux acceptance

1. Follow `linux-setup.md`, run tests, and verify `discover`/`monitor`.
2. Run `bridge`, find the virtual joystick with an input testing tool.
3. Check all axis endpoints, service B7 versus EB/button 8, hat and seven inputs.
4. Unplug USB with a button held: process should exit and release/destroy output.
5. Verify Ctrl-C and SIGTERM also release. Test keyboard mode with dry-run first.
6. Configure one chosen simulator/bridge and verify neutral, notch scaling and
   emergency behavior in a stationary train before normal gameplay.
