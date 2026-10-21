# Running Train on Linux: optional game integration

## Current boundary

For the short explanation, start with [game-integration.md](game-integration.md).
Linux input debugging has been confirmed by the operator; that is not the same
as validating a virtual-joystick or in-game connection.

The physical TCPP-20011 input protocol and display writes have been exercised on
the Mac. The driver contains Linux uinput output, but **real Linux virtual input
and Running Train integration have not yet been verified**. This is a plan, not a
working-game certification or an installed mod. Nothing has been written into a
Steam library or Proton prefix by this project.

## Recommended path: absolute axes through TSW Controller App

```
TCPP-20011 -> this driver's background service -> virtual joystick -> TSW Controller App
    -> Running Train's UE4SS controller mod -> in-game throttle/brake
```

[TSW Controller App's upstream README](https://github.com/LiahMartens/tsw-controller-app)
explicitly lists **Running Train support as beta**, with a required mod and **no
`api_control`**. Despite the name, it supports more games than Train Sim World.
It has Linux/Flatpak distributions. Its source includes a specific Running Train
installer and mod; using this existing bridge avoids implementing an invasive
game-memory hook in the USB driver.

The current Running Train mod exposes direct control names **`Throttle`**,
**`Brake`** and **`Reverser`**. These names were checked in
[the upstream Running Train mod source](https://github.com/LiahMartens/tsw-controller-app/blob/main/running-train-controller-mod/ue4ss-mod/src/dllmain.cpp).
Their actual notch ranges must be measured in your game/locomotive; the
Shinkansen's 13 power notches do not imply Running Train uses 13 power steps.

### Setup sequence

1. Follow [the common Linux setup](linux-setup.md), including udev/uinput permissions.
   Verify the real virtual joystick with a tester before installing a game mod.
2. Install a current upstream Linux build of TSW Controller App. Review its
   publisher, release notes and mod instructions. This project does not download,
   execute or redistribute its binaries/mods.
3. Back up any existing game mods/configuration. Use its **Running Train** mod
   installer, not the TSW installer. The current installer targets:
   `RunningTrain/Binaries/Win64/RunningTrain-Win64-Shipping.exe` inside the game's
   installation, as confirmed in
   [upstream installer source](https://github.com/LiahMartens/tsw-controller-app/blob/main/go-app/app_mod_installers.go).
   Locate the library through Steam's **Browse local files**; do not assume a
   fixed internal/external-drive library path. Installing a mod changes game files;
   only do this after reviewing and accepting the upstream instructions.
4. Confirm the UE4SS mod loads under the chosen Proton version. The upstream
   README's explicit Proton 9/10 guidance is for **Train Sim World**, not a
   Running Train compatibility guarantee. Do not apply TSW-specific `-HTTPAPI`
   instructions to Running Train, or guess a DLL override. Follow Running Train's
   current upstream release requirements and inspect logs if it fails to connect.
5. Install/start the [background service](background-service.md) on the Linux host.
   Plug in the controller. In the companion app,
   calibrate **open-shinkansen Virtual Joystick**: power X -> friendly name
   `Throttle`; brake Y -> `Brake`; button 8 -> `Emergency`; pedal -> `Horn`.
   Sweep each axis completely and verify its direction. SDL may normalize the
   raw device's 0..32767 range to −32768..32767.
6. In the game's cab, use the companion app's debugger to discover the live
   `Throttle` and `Brake` values at neutral, each notch, and maximum. Build
   **Direct Control** assignments for those names and measured min/max/notch
   values. Do **not** choose the TSW-only `api_control` mode. Follow its
   [profile quickstart](https://tsw-controller-app.vercel.app/docs/creating-profile-quickstart),
   but skip TSW-only HTTP API steps. No `.tswprofile` with invented ranges is
   bundled here.
7. Verify emergency separately. This driver gives B7 and EB the **same maximum
   brake axis**, with EB additionally asserting button 8. The companion profile
   must translate button 8 to Running Train's actual emergency mechanism; do not
   claim emergency works just because the service brake reaches maximum.
8. Select and test any reverser, horn and other button actions deliberately. This
   physical controller has no reverser lever, so use buttons or the game's normal
   controls for direction selection. Test stopped before attempting a route.

### Avoiding duplicate input

Only one app should command an action. Run this driver's joystick output, not its
keyboard mode, when the companion app performs the mappings. If Steam Input also
maps this virtual joystick into gamepad/keyboard actions, neutralize that mapping
for the **external virtual joystick**. Do not accidentally disable another gamepad
needed for menus. Upstream has a Steam Input guide, but its
published community layouts are TSW-specific; do not import a TSW layout blindly
for Running Train. Gaming-Mode background-app lifecycle still needs testing.

## Fallback: this driver's keyboard output

If the beta mod cannot work with the installed game/Proton build, the driver's
relative keyboard mode can send Running Train's actual increase/decrease keys.
We need the game's current bindings and locomotive notch counts before making a
usable Running Train preset. `profiles/relative-template.json` is **not** that
preset. Do not assume its A/D and semicolon/apostrophe bindings match this game.

Match game and physical controls before starting. Watch for missed/repeated
pulses and use `--dry-run` first. Exact direct-notch keys, if supported by the
game, are preferable to open-loop relative pulses.

## Information needed to validate the game integration

- Output of `open-shinkansen doctor` to check the generic service prerequisites.
- Running Train build/version, locomotive and Proton version.
- Whether USB `discover`/`monitor` and the opt-in uinput loopback test pass.
- Whether TSW Controller App sees the virtual joystick and the Running Train mod
  reports the current cab controls.
- Throttle/brake notch ranges; emergency and horn bindings.

The USB driver's own autostart/reconnect is implemented; the companion app's
autostart and game/mod calibration remain separate one-time setup. No external
app launcher is installed by this project, and end-to-end set-and-forget Running
Train operation has not yet been validated.

Automatic speed/ATC/door feedback to the physical display is **not implemented**.
The checked Running Train mod reports throttle/brake/reverser, not a ready-made
USB-display telemetry feed. Manual LED output works independently of the game.
