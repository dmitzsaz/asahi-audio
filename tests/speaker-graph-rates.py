#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise J704's fixed-rate DSP at different client and driver rates.

Needs the same tools/plugins as speaker-graph-clips.py plus pw-metadata and
pw-dump. Uses a private daemon with no device monitor or ALSA nodes. Reuses
one filter across clock changes and stream restarts; checks negotiated DSP
formats and non-silent, finite output on every channel. No hardware access.

Run: python3 tests/speaker-graph-rates.py
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave

spec = importlib.util.spec_from_file_location(
    "clips", Path(__file__).with_name("speaker-graph-clips.py"))
clips = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clips)
RATES = (44100, 48000, 96000)
CASES = ((44100, 44100), (48000, 44100), (48000, 96000),
         (96000, 96000), (48000, 48000), (44100, 48000))


def main():
    need = ("pipewire", "pw-cli", "pw-link", "pw-play", "pw-record", "pw-metadata", "pw-dump")
    if any(shutil.which(t) is None for t in need):
        print("skipped: needs " + " ".join(need))
        return 77
    with tempfile.TemporaryDirectory(prefix="speaker-graph-rates.") as top:
        off = clips.Offline("j704", top, RATES)
        try:
            for clock_rate, client_rate in CASES:
                off.rate = clock_rate
                subprocess.run(["pw-metadata", "-n", "settings", "0", "clock.force-rate", str(clock_rate)],
                               env=off.env, check=True, capture_output=True, timeout=10)
                time.sleep(0.2)
                src, dst = os.path.join(top, "in.wav"), os.path.join(top, "out.wav")
                with wave.open(src, "wb") as w:
                    w.setnchannels(2)
                    w.setsampwidth(2)
                    w.setframerate(client_rate)
                    w.writeframes(b"".join(struct.pack("<hh",
                        int(3000 * math.sin(2 * math.pi * 500 * i / client_rate)),
                        int(3000 * math.sin(2 * math.pi * 700 * i / client_rate)))
                        for i in range(client_rate * 2)))
                off.render(src, dst)
                state = json.loads(off.run("pw-dump"))
                nodes = [o["info"] for o in state if o.get("info", {}).get("props", {})
                         .get("node.name") in ("off.in", "off.out")]
                formats = [n.get("params", {}).get("Format") for n in nodes]
                stats = clips.clip_stats(dst)
                assert len(nodes) == 2 and all(n.get("state") != "error" for n in nodes), nodes
                assert all(f and f[0].get("rate") == 48000 for f in formats), formats
                assert len(stats) == 6 and all(s[0] == 0 and math.isfinite(s[2])
                                               and s[2] > -65 for s in stats), stats
                assert "can't start graph" not in Path(off.d, "log").read_text()
                print("client %d, clock %d: DSP 48000, six non-silent channels, no errors"
                      % (client_rate, clock_rate),
                      flush=True)
        except Exception:
            print(Path(off.d, "log").read_text(), file=sys.stderr)
            raise
        finally:
            off.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
