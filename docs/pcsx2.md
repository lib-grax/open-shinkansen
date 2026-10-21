# PCSX2: Shinkansen profile and Start Check

Requires **open-shinkansen 0.4.0+**. This profile targets PCSX2's emulated **USB
Train Controller / Shinkansen**, not a DualShock or the Type 2 subtype.

## 1. Select the profile

Stop emulation while changing input configuration. Exit any open `debug` session.
In the project directory:

```sh
git pull --ff-only
./setup.sh
.venv/bin/open-shinkansen profile set pcsx2-shinkansen
.venv/bin/open-shinkansen service restart
```

The selection is saved for future service starts; no emulator files are edited.
Move the handles once if the service is waiting for its first input report.
`profile show` prints the saved selection; `service logs` includes the profile
loaded by the running worker. The device name stays **open-shinkansen Virtual
Joystick**.

## 2. Set PCSX2 to match

In the desktop controller-settings window:

Make sure you edit the PCSX2 input profile used by the game (Shared, or its
assigned per-game profile). The driver profile selected in the terminal is a
separate setting; it does not automatically create an entry in PCSX2's profile
dropdown. Game Properties -> Summary -> Input Profile identifies an override.

1. Ensure SDL input is enabled and the named virtual joystick is detected.
2. Select **USB Port 1 -> Train Controller -> Shinkansen**.
3. Open that USB device's **Settings** and **enable Axes Passthrough**.
   This is axis-byte passthrough, not physical USB passthrough.
4. Open **Mapping Settings** and leave **Ignore Inversion unchecked**.
5. **Clear the old Power and Brake bindings** before assigning them again.
   Old half-axis or axis+button bindings will not become correct automatically.

**Axes Passthrough ON is specific to this profile.** Earlier advice to leave it
off applied to the generic joystick profile, which sends ordinary normalized
axes rather than values intended to reconstruct the original report bytes.

## 3. Capture the entire lever range

For **Power**:

1. Put the handle at **N** before clicking its binding.
2. Move slowly through the first notch, continue to **P13**, then return to **N**.

For **Brake**:

1. Put the handle at **released** before clicking its binding.
2. Move slowly through **B1**, continue all the way to **EB**, then return to released.

Pause briefly at the first notch: PCSX2 must observe that first small movement
before the rest of the sweep. Then finish the full sweep and return before the
on-screen binding countdown expires (usually five seconds); do not pause at
every intermediate notch. Do not press other controls while binding.

The resulting binding must be a **full-range, inverted axis**, commonly displayed
as `Full Axis ... ~` (wording varies with PCSX2/SDL version). It must **not** just
say `+Axis`/`-Axis`, and must not include an emergency button as a chord. The profile
uses positive-at-rest axes deliberately so PCSX2's pedal-style capture can detect
full travel and apply the inversion. See the named binding's tooltip if truncated.

If capture is incorrect, clear it and repeat the slow full sweep. If necessary,
Shift-click the binding to review its entries/settings: use **100% sensitivity**
and **0% deadzone**. Avoid Steam Input or another mapper duplicating/remapping
this external joystick; for first validation, run desktop PCSX2 directly.

## 4. Check the game

Follow the game's Start Check instructions, putting power at N and brake at EB
when requested. After closing the binding window, move power **N -> P1 -> N**
and cycle the brake once so the emulator receives fresh events; a handle already
at rest may not generate another event after binding capture. Do this while the
game is stopped/on its check screen, not while driving. The profile reconstructs
distinct original values:

| Position | Byte delivered through the matching PCSX2 binding |
| --- | --- |
| Brake released | `1c` |
| B7 | `df` |
| Emergency | `fb` |
| Power N | `12` |
| P13 | `fb` |

All intermediate notches are preserved too. Transitions retain the last valid
notch. In this profile, emergency travels on the **brake axis**, not button 8.

Bind A/B/C/D, Select/Start and the D-pad normally. PCSX2's Shinkansen emulation
exposes C as the horn rather than a separate pedal binding; this profile merges
the physical horn pedal into C automatically. Virtual buttons 7 and 8 remain
reserved/inactive so pedal/emergency do not form accidental binding chords.
Debug still shows the physical pedal and emergency independently.

## If Start Check still fails

Verify the saved profile, the running service's log, **Shinkansen** subtype,
**Axes Passthrough ON**, and the two **Full ... ~** bindings. If physical `debug`
does not show EB when the handle is in emergency, diagnose the USB/input path
first. Stop debug and restart the service before returning to PCSX2.

If the settings match but the check fails, provide the exact PS2 game title,
PCSX2 version, screenshot of the check, and the Power/Brake binding tooltip text.
The encoding is covered by all-notch round-trip and capture-range tests, but
**this is not yet an end-to-end game certification**. PCSX2's emulator-side
limitations (including the original separate pedal byte) cannot be fixed by
axis mapping alone.

## Switching back to ordinary PC train games

The generic profile is unchanged and remains the default:

```sh
.venv/bin/open-shinkansen profile set generic
.venv/bin/open-shinkansen service restart
```

Change profiles outside gameplay. Selection is not automatic per application.
For a temporary foreground test, stop the service and use
`bridge --joystick-profile pcsx2-shinkansen`; `--dry-run --replay FILE` can also
inspect events without hardware. A saved profile does not affect keyboard mode.

This profile adds **input compatibility only**. PCSX2's game display writes are
not forwarded to the physical speedometer/ATC/door lamp; automatic feedback
requires a separate integration. The manual `debug --outputs` tests remain
independent.

References checked: [PCSX2 train device](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/USB/usb-pad/usb-train.cpp),
[SDL axes](https://github.com/PCSX2/pcsx2/blob/master/pcsx2/Input/SDLInputSource.cpp),
[binding capture](https://github.com/PCSX2/pcsx2/blob/master/pcsx2-qt/Settings/InputBindingWidget.cpp).
