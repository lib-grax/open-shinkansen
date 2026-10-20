# Keyboard profiles

Profiles use JSON and Linux `KEY_*` identifiers. Validation runs before claiming
USB or creating virtual input. Unsupported fields, keys and notch counts fail
early rather than silently ignoring a typo. Timing defaults to 80ms down / 60ms
gap. Use a dry-run to verify behavior first.

## Buttons

Map `a`, `b`, `c`, `d`, `select`, `start`, `pedal`, `emergency`, `up`, `down`,
`left`, `right` in the `buttons` object. The key is held while active. Diagonal
D-pad directions hold two keys. Multiple controls bound to one key are merged;
releasing one does not release another's held key.

## Axis modes

- `{"mode": "disabled"}`: no keyboard output from this lever.
- `{"mode": "absolute", "keys": [...]}`: 14 entries for power (N, P1..P13),
  9 for brake (release, B1..B7, EB). `null` is unbound. Holds the selected key
  until the lever leaves that notch. Use only if the game accepts direct-notch
  keys; this is not the same as generic increase/decrease controls. Neutral/
  released should have an explicit key if your game requires one.
- `{"mode": "relative", "steps": 8, "increase": "KEY_A", "decrease": "KEY_D"}`:
  scales the full physical travel to 0..`steps`, then pulses the appropriate key
  once per changed step. The first valid reading is a baseline, with no pulses.
  `steps` may be 1..64. Power and brake pulse fairly in turn without blocking
  USB reads. Pending targets change when handles move again, using the number of
  emitted steps as reference rather than queuing obsolete movements indefinitely.

`pulse_ms` and `gap_ms` each accept 10..2000ms. Keys pressed while a game is out
of focus, a game-paused control, held-key auto-repeat, or a missed pulse can all
desynchronize relative mode. Stop/match/restart to establish a new baseline.

Emergency can be bound as a held button, independently of relative steps. Make
sure your profile does not also issue contradictory ordinary brake pulses for a
game that requires a separate emergency key. Buttons sharing a relative pulse
key delay that pulse until the held key is released; avoid overlapping bindings.
Do not use both keyboard injection and a second joystick-to-key mapper for the
same actions.
