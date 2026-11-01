#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Dmitriy <noc@pimk.in>
"""No audio devices: exercise the J704 helper's PipeWire command boundary."""
import importlib.machinery
import importlib.util
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
loader = importlib.machinery.SourceFileLoader(
    "j704_volume_eq", str(ROOT / "conf/j704-speaker-volume-eq"))
spec = importlib.util.spec_from_loader(loader.name, loader)
eq = importlib.util.module_from_spec(spec)
loader.exec_module(eq)
CONF = json.loads((ROOT / "firs/j704/volume-eq.json").read_text())


class VolumeEQ(unittest.TestCase):
    def test_bank_crossfades_preserve_unity_and_stay_nonnegative(self):
        for i in range(-20, 121):
            weights = eq.weights(i / 100, CONF["banks"], CONF["exponent"])
            self.assertAlmostEqual(sum(weights), 1)
            self.assertTrue(all(0 <= x <= 1 for x in weights))
            self.assertLessEqual(sum(x > 0 for x in weights), 2)

    def test_endpoint_banks(self):
        self.assertEqual(eq.weights(0, CONF["banks"], 3), [1, 0, 0, 0])
        self.assertEqual(eq.weights(1, CONF["banks"], 3), [0, 0, 0, 1])

    def test_gain_compensation_is_bounded_and_restored(self):
        for volume in (0, 0.001, 0.1, 0.343, 0.5, 1, 1.5):
            with patch.object(eq.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess([], 0)
                weights = eq.weights(volume, CONF["banks"], CONF["exponent"])
                self.assertTrue(eq.apply(17, CONF, weights, volume))
                args = run.call_args.args[0]
            self.assertEqual(args[:4], ["pw-cli", "set-param", "17", "Props"])
            tokens = shlex.split(args[4].split("[", 1)[1].split("]", 1)[0])
            values = {tokens[i].strip('"'): float(tokens[i + 1])
                      for i in range(0, len(tokens), 2)}
            self.assertTrue(all(math.isfinite(x) for x in values.values()))
            for side in "LR":
                pre = values[f"pre{side}1:Mult"] * values[f"pre{side}2:Mult"]
                post = values[f"post{side}:Mult"]
                self.assertLessEqual(pre, 100.00001)
                self.assertAlmostEqual(pre * post, 1, places=4)
                self.assertTrue(all(values[f"pre{side}{n}:Mult"] <= 10 for n in (1, 2)))
            for bank, ports in enumerate(CONF["mixers"]["aL"]):
                for port in ports:
                    self.assertAlmostEqual(values[f"aL:Gain {port}"], weights[bank], places=4)

    def test_control_write_failure_is_reported_for_reconnection(self):
        with patch.object(eq.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 1)
            self.assertFalse(eq.apply(17, CONF, [1, 0, 0, 0], 1))

    def test_sink_lookup_ignores_other_objects_and_names(self):
        objects = [{"id": 2, "type": "PipeWire:Interface:Device",
                    "info": {"props": {"node.name": CONF["node"]}}},
                   {"id": 3, "type": "PipeWire:Interface:Node",
                    "info": {"props": {"node.name": "another-sink"}}},
                   {"id": 17, "type": "PipeWire:Interface:Node",
                    "info": {"props": {"node.name": CONF["node"]}}}]
        with patch.object(eq.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, json.dumps(objects))
            self.assertEqual(eq.node_id(CONF["node"]), 17)

    def test_sink_lookup_tolerates_pipewire_restart(self):
        with patch.object(eq.subprocess, "run", side_effect=subprocess.TimeoutExpired("pw-dump", 5)):
            self.assertIsNone(eq.node_id(CONF["node"]))

    def test_volume_read_after_sink_disappears(self):
        with patch.object(eq.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 1, "")
            self.assertIsNone(eq.volume(17))


if __name__ == "__main__":
    unittest.main()
