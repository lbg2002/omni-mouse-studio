"""Hardware-free performance, configuration and input safety regression tests."""
from __future__ import annotations

import errno
import os
import tempfile
import threading
import unittest
from unittest import mock

from omni_mouse.config.profiles import ActionSpec, DriverConfig, load_config, save_config, update_config
from omni_mouse.daemon import linux_input as li
from omni_mouse.daemon.engine import SmartMouseDaemon


class TestConfigPersistence(unittest.TestCase):
    def test_corruption_recovers_last_good_backup_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            cfg = DriverConfig()
            cfg.preferred_model = "inphic_w1"
            save_config(cfg, path)
            cfg.preferred_model = "delux_m618xsd"
            save_config(cfg, path)
            with open(path, "w", encoding="utf-8") as fd:
                fd.write("{ malformed")
            recovered = load_config(path)
            self.assertEqual(recovered.preferred_model, "inphic_w1")
            self.assertEqual(load_config(path + ".bak").preferred_model, "inphic_w1")
            self.assertEqual(sorted(os.listdir(directory)), ["config.json", "config.json.bak"])

    def test_locked_updates_preserve_simultaneous_independent_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            save_config(DriverConfig(), path)
            barrier = threading.Barrier(2)
            exceptions = []

            def change(key, value):
                try:
                    barrier.wait(timeout=4)
                    update_config(lambda cfg: setattr(cfg, key, value), path)
                except Exception as exc:
                    exceptions.append(exc)

            threads = [
                threading.Thread(target=change, args=("per_app_enabled", False)),
                threading.Thread(target=change, args=("preferred_model", "inphic_w1")),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertFalse(exceptions)
            cfg = load_config(path)
            self.assertFalse(cfg.per_app_enabled)
            self.assertEqual(cfg.preferred_model, "inphic_w1")
            self.assertFalse(any(p.startswith(".omni-") for p in os.listdir(directory)))


class TestInputSafety(unittest.TestCase):
    def test_selected_model_never_falls_back_to_other_mouse(self):
        node = li.EvdevMouseNode("/dev/input/event7", "Delux", 0x1d57, 0xfa60, "delux_m618xsd")
        with mock.patch.object(li, "list_supported_mouse_evdev", return_value=[node]):
            self.assertIsNone(li.find_supported_mouse_evdev("inphic_w1"))
            self.assertEqual(li.find_supported_mouse_evdev(None), node)

    def test_syn_dropped_aborts_invalid_event_stream(self):
        reader = li.PhysicalMouseReader("/dev/input/event7")
        reader.fd = 99
        raw = li.EVENT_STRUCT.pack(0, 0, li.EV_SYN, li.SYN_DROPPED, 0)
        with mock.patch.object(li.os, "read", return_value=raw):
            with self.assertRaises(OSError) as error:
                reader.read_events()
        self.assertEqual(error.exception.errno, errno.EOVERFLOW)

    def test_keyboard_release_after_failed_mouse_zoom(self):
        pair = li.VirtualInputPair()
        pair.kbd_fd = 10
        pair.mouse_fd = 11
        writes = []

        def emit(fd, events):
            writes.append((fd, list(events)))
            if fd == 11:
                raise OSError(errno.EIO, "mouse injection failed")

        with mock.patch.object(pair, "_write", side_effect=emit), mock.patch.object(li.time, "sleep"):
            with self.assertRaises(OSError):
                pair.emit_zoom(1)
        self.assertEqual(writes[0][0], 10)
        self.assertIn((li.EV_KEY, li.KEY_LEFTCTRL, 0), writes[-1][1])

    def test_bounded_action_queue_does_not_block_mouse_input(self):
        daemon = SmartMouseDaemon()
        daemon._action_thread = threading.current_thread()  # mark worker as active
        try:
            spec = ActionSpec(kind="key_combo", combo="Ctrl+Tab")
            for _ in range(65):
                daemon._execute_action(spec, source_label="high rate scroll")
            self.assertEqual(daemon._action_queue.qsize(), 64)
            self.assertEqual(daemon._dropped_actions, 1)
        finally:
            daemon._action_thread = None

    def test_one_worker_serializes_shortcuts(self):
        daemon = SmartMouseDaemon()
        calls = []
        daemon.virtual.emit_key_combo = lambda codes: calls.append(codes)
        worker = threading.Thread(target=daemon._action_worker, daemon=True)
        daemon._action_thread = worker
        worker.start()
        try:
            for _ in range(4):
                daemon._execute_action(ActionSpec(kind="key_combo", combo="Ctrl+Tab"))
            daemon._action_queue.join()
            self.assertEqual(calls, [[29, 15]] * 4)
        finally:
            daemon._action_stop.set()
            worker.join(timeout=2)
            daemon._action_thread = None


if __name__ == "__main__":
    unittest.main()
