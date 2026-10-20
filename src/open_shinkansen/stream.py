"""Timed JSONL capture/replay. Idle USB reads still tick the output scheduler."""

import json
import math
import time
from contextlib import contextmanager
from pathlib import Path


def replay_records(path):
    previous = -1.0
    with Path(path).open(encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                at = record["t"]
                if type(at) not in (int, float) or not math.isfinite(at) or at < max(0, previous):
                    raise ValueError("t must be finite, nonnegative and nondecreasing")
                raw = bytes.fromhex(record["raw"])
                if len(raw) not in (6, 8):
                    raise ValueError("raw must encode 6 or 8 bytes")
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"Invalid capture {path}, line {number}: {exc}") from exc
            previous = at
            yield float(at), raw


def samples(read=None, replay=None, duration=None):
    start = time.monotonic()
    records = iter(replay_records(replay)) if replay else None
    pending = next(records, None) if records is not None else None
    while True:
        elapsed = time.monotonic() - start
        if duration is not None and elapsed >= duration:
            return
        if records is None:
            # Controller read is bounded to 20ms so releases are not delayed by idle USB.
            raw = read()
            yield time.monotonic() - start, raw
        else:
            if pending is None:
                return
            at, raw = pending
            if elapsed >= at:
                yield elapsed, raw
                pending = next(records, None)
            else:
                time.sleep(min(0.01, at - elapsed))
                yield time.monotonic() - start, None


@contextmanager
def recorder(path):
    # Never truncate an existing capture, including a replay input file.
    handle = Path(path).open("x", encoding="utf-8") if path else None

    def write(at, raw):
        if handle is not None and raw is not None:
            handle.write(json.dumps({"t": round(at, 6), "raw": raw.hex(" ")}) + "\n")
            handle.flush()

    try:
        yield write
    finally:
        if handle is not None:
            handle.close()
