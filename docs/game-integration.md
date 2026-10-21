# How does the controller communicate with a game?

## What open-shinkansen currently does

It translates Taito's unusual USB protocol into a **standard virtual joystick**:

```
Physical controller -> open-shinkansen service -> Linux virtual joystick
```

The virtual joystick is named **open-shinkansen Virtual Joystick**. It has power
and brake axes, buttons and a D-pad. A game that supports configurable joystick
input can bind these directly. Being recognized by Linux does **not** guarantee
every game accepts arbitrary joysticks or knows what a train handle represents.

`debug` is a separate hardware test. It reads the USB device directly and creates
no virtual joystick. Exit debug and start the service before testing a game.

## Running Train

There is **not yet a tested, automatic Running Train connection** in this project.
The planned path reuses an existing game-aware tool:

```
Controller -> open-shinkansen -> virtual joystick
    -> TSW Controller App -> Running Train controller mod -> game controls
```

[TSW Controller App](https://github.com/LiahMartens/tsw-controller-app) supports
multiple simulators despite its name. Its upstream README lists Running Train
support as **beta**, requiring a game mod. We have not verified this combination
with open-shinkansen, your game version or your selected locomotive.

The remaining one-time work is to install a compatible companion app/mod,
calibrate this virtual joystick, bind throttle/brake/emergency/horn, and verify
them in a stationary train. The companion app also needs to be running when you
play. Its autostart and game-specific setup are **not installed by setup.sh**.
The detailed [Running Train plan](running-train.md) covers the known control
names, calibration and safety checks. No guessed game profile is bundled.

## Other games

- **Native joystick support:** bind the named device in the game's settings.
- **Game-specific bridge/API:** use a suitable adapter for that game.
- **Keyboard-only controls:** the optional keyboard output can send configured
  keystrokes, but each game/locomotive needs appropriate bindings and timing.
  Relative key pulses can drift; prefer direct axes/API control when available.

Open-shinkansen's input protocol does not need rewriting for each game, but the
game-facing mapping may be different. There is no single universal train-game API.

## What about the speedometer, ATC and door light?

That is a **separate reverse direction**:

```
Game speed / speed-limit / door data -> game-specific feedback adapter
    -> open-shinkansen USB output -> physical controller displays
```

A virtual joystick normally sends input **to** a game; it does not supply train
speed or signalling data back to this driver. Automatic feedback requires a
supported game telemetry source and an adapter. That feedback adapter and a
daemon interface for external display updates are **not implemented yet**.

`debug --outputs` proves that manual USB display commands work; it does not read
or synchronize game data. The previously researched Running Train mod reports
throttle/brake/reverser, not a ready-made speed/ATC/door telemetry feed. ATC speed
limit data may not be exposed by a particular game/train at all.

Do not launch a second raw-USB writer while the daemon owns the controller.
A future feedback path needs to send updates through the process that owns USB,
rather than have two applications compete for it.
