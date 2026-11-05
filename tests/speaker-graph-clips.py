#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that no speaker graph sends samples over full scale to the amps.

The amplifiers take integer samples, so anything a graph outputs at or over
1.0 is hard-clipped at the float-to-integer conversion, before the amp's
own gain and before any speaker-protection daemon can act.  The compressor
that ends the shared graph shape (woofer_lim: 0 dBFS, 15:1, 1 ms attack)
lets transients through, so every output must come from a brick-wall
limiter.

Two parts:

1. Static, runs anywhere: every graph output is fed by an LSP limiter
   (limiter_stereo) at -0.5 dBFS or lower with lookahead and no level
   regulation or boost, and every output limiter of a graph has the same
   settings, so every output path keeps the same latency relative to the
   others (woofers and tweeters stay aligned).

2. Offline render, needs pipewire, pw-cat, pw-link and pw-cli with the
   LV2 plugins the graphs use (bankstown, lsp-plugins): each graph runs in
   a private PipeWire daemon that has no ALSA plugin, no device monitor and
   no session manager, so nothing can reach a speaker.  Three generated
   signals play through it at 100 % (the capture volume at 0 dB):
     - pink noise at -12 dBFS RMS,
     - a 30-300 Hz logarithmic sweep at -3 dBFS peak,
     - kick drums plus bass-heavy pink noise, mastered to -1 dBFS peak with
       a 10 dB crest factor.
   Every output channel must stay under full scale: zero clipped samples.
   The render runs in real time, about 30 s per graph, all graphs at once.

Run: python3 tests/speaker-graph-clips.py [--static] [jNNN ...]
Exit 77 means the render part was skipped because PipeWire or a plugin is
missing; the static part still ran.
"""
import array
import json
import math
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRS = os.path.join(ROOT, "firs")
RATE = 48000
LIMITER = "http://lsp-plug.in/plugins/lv2/limiter_stereo"
MAX_TH = 0.9441          # -0.5 dBFS
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def load(path):
    """The graphs are SPA JSON: trailing commas, # comments."""
    with open(path) as f:
        text = "\n".join(l for l in f.read().split("\n") if not l.lstrip().startswith("#"))
    return json.loads(re.sub(r",(\s*[\]}])", r"\1", text))


def boards(argv):
    names = [a for a in argv if not a.startswith("-")]
    have = sorted(d for d in os.listdir(FIRS) if os.path.exists(os.path.join(FIRS, d, "graph.json")))
    return names or have


# ---- 1. static -------------------------------------------------------------

def static_check(board):
    g = load(os.path.join(FIRS, board, "graph.json"))["filter.graph"]
    nodes = {n["name"]: n for n in g["nodes"]}
    feeds = {}                       # input port -> output port
    for l in g["links"]:
        feeds[l["input"]] = l["output"]
    seen = []
    for out in g["outputs"]:
        name = out.split(":")[0]
        # copies only duplicate a channel; follow them back
        while nodes[name].get("label") == "copy":
            name = feeds[name + ":In"].split(":")[0]
        n = nodes[name]
        if n.get("plugin") != LIMITER:
            check(False, "%s: output %s is fed by %s, not a brick-wall limiter" % (board, out, name))
            continue
        c = n.get("control", {})
        check(c.get("th", 1.0) <= MAX_TH, "%s: %s threshold %s is over -0.5 dBFS" % (board, name, c.get("th")))
        check(c.get("lk", 5.0) > 0 and c.get("alr", 1) == 0 and c.get("boost", 1) == 0,
              "%s: %s needs lookahead, alr 0 and boost 0" % (board, name))
        seen.append((name, json.dumps(c, sort_keys=True)))
    check(len({c for _, c in seen}) <= 1,
          "%s: output limiters differ, so the output paths would not keep their alignment: %s" % (board, seen))


# ---- 2. offline render -----------------------------------------------------

def write_wav(path, frames):
    """Stereo float32 WAV from a list of (l, r)."""
    data = array.array("f", [s for fr in frames for s in fr]).tobytes()
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
                + struct.pack("<IHHIIHH", 16, 3, 2, RATE, RATE * 8, 8, 32)
                + b"data" + struct.pack("<I", len(data)) + data)


def read_wav_f32(path):
    with open(path, "rb") as f:
        b = f.read()
    i, ch, data = 12, None, None
    while i + 8 <= len(b):
        cid, n = b[i:i + 4], struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"fmt ":
            ch = struct.unpack("<H", b[i + 10:i + 12])[0]
        if cid == b"data":
            data = b[i + 8:] if n in (0, 0xFFFFFFFF) or i + 8 + n > len(b) else b[i + 8:i + 8 + n]
            break
        i += 8 + n + (n & 1)
    a = array.array("f")
    a.frombytes(data[:len(data) // (4 * ch) * 4 * ch])
    return ch, a


def fade(x, n=int(0.02 * RATE)):
    for k in range(min(n, len(x) // 2)):
        g = k / n
        x[k] *= g
        x[-1 - k] *= g
    return x


def pink(n, rng, lowpass_hz=None):
    """Paul Kellet's pink filter on white noise, optionally one-pole low-passed."""
    b = [0.0] * 7
    a = math.exp(-2 * math.pi * lowpass_hz / RATE) if lowpass_hz else 0.0
    y, out = 0.0, []
    for _ in range(n):
        w = rng.gauss(0, 1)
        b[0] = 0.99886 * b[0] + w * 0.0555179
        b[1] = 0.99332 * b[1] + w * 0.0750759
        b[2] = 0.96900 * b[2] + w * 0.1538520
        b[3] = 0.86650 * b[3] + w * 0.3104856
        b[4] = 0.55000 * b[4] + w * 0.5329522
        b[5] = -0.7616 * b[5] - w * 0.0168980
        p = sum(b) + b[6] + w * 0.5362
        b[6] = w * 0.115926
        y = a * y + (1 - a) * p
        out.append(y)
    return out


def scale_rms(x, db):
    r = math.sqrt(sum(v * v for v in x) / len(x))
    g = 10 ** (db / 20) / r
    return [v * g for v in x]


def signals(d):
    rng = random.Random(1)
    lead = [(0.0, 0.0)] * (RATE // 2)
    n = 8 * RATE
    # pink noise, -12 dBFS RMS, independent channels
    l, r = fade(scale_rms(pink(n, rng), -12)), fade(scale_rms(pink(n, rng), -12))
    write_wav(os.path.join(d, "pink-12.wav"), lead + [(max(-1, min(1, a)), max(-1, min(1, b))) for a, b in zip(l, r)])
    # 30-300 Hz log sweep, -3 dBFS peak
    f0, f1, T = 30.0, 300.0, 8.0
    k = math.log(f1 / f0)
    s = fade([0.708 * math.sin(2 * math.pi * f0 * T / k * (math.exp(t / RATE / T * k) - 1)) for t in range(n)])
    write_wav(os.path.join(d, "bass-sweep.wav"), lead + [(v, v) for v in s])
    # kicks (55 Hz, 120 bpm) over bass-heavy pink noise, -1 dBFS peak, ~10 dB crest
    bed = scale_rms(pink(n, rng, lowpass_hz=400), -16)
    m = []
    for t in range(n):
        tk = (t % (RATE // 2)) / RATE
        kick = math.exp(-tk / 0.12) * math.sin(2 * math.pi * (55 + 90 * math.exp(-tk / 0.02)) * tk)
        m.append(bed[t] + 0.6 * kick)
    pk = max(abs(v) for v in m)
    m = fade([v * 10 ** (-1 / 20) / pk for v in m])
    write_wav(os.path.join(d, "kick-bass.wav"), lead + [(v, v) for v in m])
    return ["pink-12", "bass-sweep", "kick-bass"]


def offline_conf(board, d, rates=(RATE,)):
    g = load(os.path.join(FIRS, board, "graph.json"))
    text = json.dumps(g).replace("/usr/share/asahi-audio/", FIRS + "/")
    g = json.loads(text)
    pp = g["playback.props"]
    # Keep the graph's actual stream formats and resampler settings. Replacing
    # these properties would hide rate-negotiation bugs in fixed-rate DSPs.
    args = g
    args.update({"node.description": "offline render", "media.name": "offline render",
                 "remote.name": "pipewire-off"})
    args["capture.props"].update({"node.name": "off.in", "node.autoconnect": False})
    pp.update({"node.name": "off.out", "node.autoconnect": False})
    pp.pop("target.object", None)
    pp.pop("node.passive", None)
    libs = {"audio.convert.*": "audioconvert/libspa-audioconvert", "support.*": "support/libspa-support"}
    daemon = {
        "context.properties": {"core.daemon": True, "core.name": "pipewire-off", "support.dbus": False,
                               "default.clock.rate": RATE, "default.clock.allowed-rates": list(rates),
                               "default.clock.quantum": 1024, "default.clock.min-quantum": 1024,
                               "default.clock.max-quantum": 1024, "mem.allow-mlock": False},
        "context.spa-libs": libs,
        "context.modules": [{"name": "libpipewire-module-" + m} for m in
                            ("protocol-native", "client-node", "adapter", "link-factory",
                             "spa-node-factory", "access", "metadata")],
        "context.objects": [{"factory": "spa-node-factory",
                             "args": {"factory.name": "support.node.driver", "node.name": "Dummy-Driver",
                                      "node.group": "pipewire.dummy", "priority.driver": 20000}}],
    }
    client = {
        "context.properties": {"support.dbus": False, "remote.name": "pipewire-off"},
        "context.spa-libs": libs,
        "context.modules": [{"name": "libpipewire-module-" + m} for m in ("protocol-native", "client-node", "adapter")]
                           + [{"name": "libpipewire-module-filter-chain", "args": args}],
    }
    for name, c in (("daemon.conf", daemon), ("filter.conf", client)):
        with open(os.path.join(d, name), "w") as f:
            f.write("\n".join("%s = %s" % (k, json.dumps(v).replace("}, {", "} {"))
                              for k, v in c.items()) + "\n")
    return int(pp["audio.channels"])


class Offline:
    """One private PipeWire daemon plus the graph as a filter-chain client."""

    def __init__(self, board, top, rates=(RATE,)):
        self.d = tempfile.mkdtemp(prefix=board + ".", dir=top)
        self.rate = RATE
        self.n_out = offline_conf(board, self.d, rates)
        self.env = dict(os.environ, XDG_RUNTIME_DIR=self.d, PIPEWIRE_RUNTIME_DIR=self.d,
                        PIPEWIRE_REMOTE="pipewire-off")
        self.env.pop("PIPEWIRE_CORE", None)
        self.log = open(os.path.join(self.d, "log"), "w")
        self.procs = [self.spawn(["pipewire", "-c", os.path.join(self.d, "daemon.conf")])]
        self.wait(lambda: os.path.exists(os.path.join(self.d, "pipewire-off")), "daemon socket")
        self.procs.append(self.spawn(["pipewire", "-c", os.path.join(self.d, "filter.conf")]))
        self.wait(lambda: self.node("off.in") and self.node("off.out"), "filter nodes")
        self.portcfg("off.in", "Input", ["FL", "FR"])
        self.portcfg("off.out", "Output", ["AUX%d" % i for i in range(self.n_out)])

    def spawn(self, cmd):
        return subprocess.Popen(cmd, env=self.env, stdout=self.log, stderr=self.log)

    def run(self, *cmd):
        return subprocess.run(cmd, env=self.env, capture_output=True, text=True, timeout=10).stdout

    def wait(self, cond, what, t=10.0):
        end = time.time() + t
        while time.time() < end:
            if cond():
                return
            time.sleep(0.05)
        raise RuntimeError("timed out waiting for " + what)

    def node(self, name):
        cur = None
        for line in self.run("pw-cli", "ls", "Node").split("\n"):
            m = re.match(r"\s*id (\d+),", line)
            if m:
                cur = m.group(1)
            if re.match(r'\s*node\.name = "%s"$' % re.escape(name), line):
                return cur
        return None

    def portcfg(self, name, direction, pos):
        # what a session manager does: put the adapter in DSP mode
        fmt = {"mediaType": "audio", "mediaSubtype": "raw", "format": "F32P", "rate": self.rate,
               "channels": len(pos), "position": pos}
        self.run("pw-cli", "s", self.node(name), "PortConfig",
                 json.dumps({"direction": direction, "mode": "dsp", "monitor": False, "format": fmt}))

    def ports(self, flag, node):
        def key(p):
            m = re.search(r"(\d+)$", p)
            return (re.sub(r"\d+$", "", p), int(m.group(1)) if m else -1)
        return sorted((p for p in self.run("pw-link", flag).split("\n") if p.startswith(node + ":")), key=key)

    def render(self, src, dst):
        rec = self.spawn(["pw-record", "-P", "{ node.autoconnect = false node.name = off.rec }",
                          "--rate", str(self.rate), "--channels", str(self.n_out),
                          "--channel-map", ",".join("AUX%d" % i for i in range(self.n_out)),
                          "--format", "f32", dst])
        self.wait(lambda: self.node("off.rec"), "recorder")
        self.portcfg("off.rec", "Input", ["AUX%d" % i for i in range(self.n_out)])
        play = self.spawn(["pw-play", "-P", "{ node.autoconnect = false node.name = off.play }", src])
        self.wait(lambda: self.node("off.play"), "player")
        self.portcfg("off.play", "Output", ["FL", "FR"])
        self.wait(lambda: len(self.ports("-o", "off.play")) == 2 and len(self.ports("-i", "off.rec")) == self.n_out,
                  "ports")
        for a, b in zip(self.ports("-o", "off.out"), self.ports("-i", "off.rec")):
            self.run("pw-link", a, b)
        for a, b in zip(self.ports("-o", "off.play"), self.ports("-i", "off.in")):
            self.run("pw-link", a, b)
        play.wait(timeout=60)
        time.sleep(0.5)
        rec.terminate()
        rec.wait(timeout=10)

    def close(self):
        for p in reversed(self.procs):
            p.terminate()
            p.wait(timeout=10)
        self.log.close()


def clip_stats(path):
    ch, a = read_wav_f32(path)
    out = []
    for c in range(ch):
        x = a[c::ch]
        over = sum(1 for v in x if abs(v) >= 1.0)
        pk = max((abs(v) for v in x), default=0.0)
        rms = math.sqrt(sum(v * v for v in x) / max(len(x), 1))
        out.append((over, 20 * math.log10(max(pk, 1e-12)), 20 * math.log10(max(rms, 1e-12))))
    return out


def render_check(names):
    need = ["pipewire", "pw-cli", "pw-link", "pw-play", "pw-record"]
    if any(shutil.which(t) is None for t in need):
        print("render: skipped, needs " + " ".join(need))
        return 77
    top = tempfile.mkdtemp(prefix="speaker-graph-clips.")
    try:
        sigs = signals(top)
        import concurrent.futures as cf

        def one(board):
            res = {}
            off = Offline(board, top)
            try:
                for s in sigs:
                    dst = os.path.join(off.d, s + ".out.wav")
                    off.render(os.path.join(top, s + ".wav"), dst)
                    res[s] = clip_stats(dst)
            finally:
                off.close()
            return board, res

        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            for board, res in ex.map(one, names):
                for s, st in res.items():
                    over = [o for o, _, _ in st]
                    print("%-5s %-10s clipped samples %s  peak %s dBFS  rms %s dBFS" % (
                        board, s, over, " ".join("%.2f" % p for _, p, _ in st),
                        " ".join("%.1f" % r for _, _, r in st)))
                    check(sum(over) == 0, "%s: %s clipped %d samples" % (board, s, sum(over)))
                    check(max(r for _, _, r in st) > -60, "%s: %s rendered silence" % (board, s))
    finally:
        shutil.rmtree(top, ignore_errors=True)
    return 0


def main():
    names = boards(sys.argv[1:])
    for b in names:
        static_check(b)
    rc = 0
    if "--static" not in sys.argv:
        try:
            rc = render_check(names)
        except (RuntimeError, subprocess.SubprocessError, OSError) as e:
            failures.append("render failed: %s" % e)
    for f in failures:
        print("FAIL: " + f)
    if failures:
        return 1
    print("ok: %d graphs%s" % (len(names), "" if rc == 0 and "--static" not in sys.argv else " (static only)"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
