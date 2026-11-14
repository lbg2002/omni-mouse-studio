#!/usr/bin/python3
"""Automated unit & live hardware round-trip verification tests for Delux M618XSD Studio."""

from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from omni_mouse.config.profiles import ActionSpec, DriverConfig
from omni_mouse.hardware import protocol as hp
from omni_mouse.hardware.keymap import parse_combo_to_evdev
from omni_mouse.hardware.session import M618XSDSession, list_m618xsd_nodes


class TestM618XSDProtocol(unittest.TestCase):
    def setUp(self) -> None:
        backup_path = os.path.join(ROOT, "factory_backup.json")
        with open(backup_path, encoding="utf-8") as fh:
            self.factory = json.load(fh)

    def test_factory_dpi_byte_exact_roundtrip(self) -> None:
        raw = bytes.fromhex(self.factory["0x04"])
        parsed = hp.DpiSettings.from_bytes(raw, verify=True)
        self.assertEqual(parsed.dpi[:5], [800, 1200, 1600, 2400, 4000])
        self.assertEqual(parsed.current_stage, 2)
        self.assertEqual(parsed.active_stages, 0x1F)
        rebuilt = bytes(parsed.build())
        self.assertEqual(rebuilt, raw, "Rebuilt DPI report must match M618XSD factory bytes 100%!")

    def test_factory_lighting_byte_exact_roundtrip(self) -> None:
        raw = bytes.fromhex(self.factory["0x05"])
        parsed = hp.LightingSettings.from_bytes(raw, verify=True)
        self.assertEqual(parsed.brightness, 8)
        self.assertEqual(parsed.led_speed, 3)
        self.assertEqual(parsed.deep_sleep_minutes, 10)
        self.assertEqual(parsed.debounce_ms, 8)
        rebuilt = bytes(parsed.build())
        self.assertEqual(rebuilt, raw, "Rebuilt Lighting report must match M618XSD factory bytes 100%!")

        stream_raw = bytes.fromhex("050f018003a800ff000104022f0000")
        stream_parsed = hp.LightingSettings.from_bytes(stream_raw, verify=True)
        self.assertEqual(stream_parsed.mode, 8)
        self.assertEqual(stream_parsed.mode_key, "stream")
        self.assertEqual(bytes(stream_parsed.build()), stream_raw)

    def test_factory_polling_byte_exact_roundtrip(self) -> None:
        raw = bytes.fromhex(self.factory["0x06"])
        parsed = hp.PollingRate.from_bytes(raw)
        self.assertEqual(parsed.hz, 250)
        self.assertEqual(bytes(parsed.build()), raw)

    def test_factory_buttons_byte_exact_roundtrip(self) -> None:
        raw = bytes.fromhex(self.factory["0x08"])
        parsed = hp.ButtonSettings.from_bytes(raw, verify=True)
        self.assertEqual(parsed.slot(1).action, 0x02)   # Left
        self.assertEqual(parsed.slot(3).action, 0x06)   # Forward
        self.assertEqual(parsed.slot(4).action, 0x05)   # Backward
        self.assertEqual(parsed.slot(15).action, 0x0B)  # Thumb wheel up/left
        self.assertEqual(parsed.slot(16).action, 0x0C)  # Thumb wheel down/right
        self.assertEqual(bytes(parsed.build()), raw, "Rebuilt Button report must match M618XSD factory bytes 100%!")

    def test_per_app_profile_matching_and_keymap(self) -> None:
        cfg = DriverConfig()
        p_chrome = cfg.resolve_profile("google-chrome.desktop", "Google-chrome", "GitHub - Google Chrome")
        self.assertEqual(p_chrome.id, "browsers")
        self.assertEqual(p_chrome.get_binding("thumb_down").combo, "Ctrl+Tab")

        p_ide = cfg.resolve_profile("antigravity-app.desktop", "Antigravity", "main.py")
        self.assertEqual(p_ide.id, "code_ide")

        p_pdf = cfg.resolve_profile("org.gnome.Evince.desktop", "evince", "manual.pdf")
        self.assertEqual(p_pdf.id, "pdf_design")
        self.assertEqual(p_pdf.get_binding("thumb_up").kind, "zoom")

        p_loupe = cfg.resolve_profile("loupe", "图像查看器", "photo.png")
        self.assertEqual(p_loupe.id, "pdf_design")

        p_wps_pdf = cfg.resolve_profile("wps", "WPS Office", "说明书.pdf - WPS Office")
        self.assertEqual(p_wps_pdf.id, "pdf_design")

        p_wps_doc = cfg.resolve_profile("wps", "WPS Office", "报告.docx - WPS文字")
        self.assertEqual(p_wps_doc.id, "wps_office")

        # Short WPS pattern "et" must NEVER hijack IDE/terminal windows whose title contains "et" (e.g. "Greeting", "WeTab")
        p_ide_greeting = cfg.resolve_profile("antigravity-app.desktop", "antigravity", "Friendly Greeting - Outside")
        self.assertEqual(p_ide_greeting.id, "code_ide")
        p_term_target = cfg.resolve_profile("org.gnome.Ptyxis", "org.gnome.Ptyxis", "dugubaoguo@host: ~/target")
        self.assertEqual(p_term_target.id, "global")

        macro_spec = ActionSpec(
            kind="macro",
            macro_steps=[{"combo": "Ctrl+C", "delay_ms": 40}, {"combo": "Ctrl+V", "delay_ms": 40}],
        )
        restored = ActionSpec.from_dict(macro_spec.to_dict())
        self.assertEqual(restored.kind, "macro")
        self.assertEqual(len(restored.macro_steps or []), 2)

        self.assertEqual(parse_combo_to_evdev("Ctrl+Shift+Tab"), [29, 42, 15])
        self.assertEqual(parse_combo_to_evdev("Ctrl+="), [29, 13])
        self.assertEqual(parse_combo_to_evdev("Ctrl+-"), [29, 12])
        self.assertEqual(parse_combo_to_evdev("Super+PageUp"), [125, 104])

    def test_daemon_gesture_never_freezes_cursor_on_dropped_release(self) -> None:
        import time
        from omni_mouse.daemon.engine import SmartMouseDaemon
        from omni_mouse.daemon.linux_input import BTN_LEFT, BTN_SIDE, EV_KEY, EV_REL, EV_SYN, REL_X

        emitted: list[list[tuple[int, int, int]]] = []
        daemon = SmartMouseDaemon()
        daemon.virtual.emit_mouse = lambda evs, sync=True: emitted.append(list(evs))  # type: ignore[method-assign]
        daemon.virtual.emit_key_combo = lambda codes: None  # type: ignore[method-assign]

        # Simulate BTN_SIDE pressed (value=1) with NO release (dropped 2.4G packet)
        daemon._process_batch_safe([(EV_KEY, BTN_SIDE, 1), (EV_SYN, 0, 0)])
        self.assertIsNotNone(daemon._gesture)

        # Age gesture past 0.50s and verify REL_X passes through freely without freezing
        daemon._gesture.started_at = time.monotonic() - 0.55
        emitted.clear()
        daemon._process_batch_safe([(EV_REL, REL_X, 18), (EV_SYN, 0, 0)])
        self.assertTrue(any(c == REL_X and v == 18 for batch in emitted for (_, c, v) in batch))

        # Left click immediately cancels any stuck gesture state
        daemon._process_batch_safe([(EV_KEY, BTN_LEFT, 1), (EV_SYN, 0, 0)])
        self.assertIsNone(daemon._gesture)

        # Verify passive battery report 0x03 decoding
        bat = hp.decode_interrupt_event(bytes.fromhex("0328400149"))
        self.assertIsInstance(bat, hp.BatteryEvent)
        self.assertEqual(bat.percent, 73)

    def test_inphic_w1_protocol_and_virtual_side_wheel(self) -> None:
        from omni_mouse.daemon.engine import SmartMouseDaemon
        from omni_mouse.daemon.linux_input import BTN_EXTRA, EV_KEY, EV_REL, EV_SYN, REL_WHEEL
        from omni_mouse.hardware.inphic_w1 import (
            InphicCpiEvent,
            InphicW1State,
            build_inphic_button_packets,
            build_inphic_dpi_packets,
            build_inphic_lighting_packet,
            decode_inphic_interrupt,
        )
        from omni_mouse.ui.server import MODEL_CAPABILITIES

        # 1. Verify 8-byte Feature Report 0x07 packets for Instant A704 (30fa:1701)
        led_off = build_inphic_lighting_packet(0x17)
        self.assertEqual(len(led_off), 8)
        self.assertEqual(led_off[:4], bytes([0x07, 0x13, 0x7F, 0x17]))

        dpi_pkts = build_inphic_dpi_packets([800, 1200, 2400, 3000], [True, True, True, True], current_stage=2)
        self.assertEqual(len(dpi_pkts), 4)
        # Stage 2 selected -> active_idx=1, 1200 CPI -> nibble=6 -> (6 << 4) | 0x09 = 0x69, mask=0x0F
        self.assertEqual(dpi_pkts[1][:5], bytes([0x07, 0x09, 0x01, 0x69, 0x0F]))
        # 3000 CPI -> nibble=15 -> (15 << 4) | 0x0B = 0xFB
        self.assertEqual(dpi_pkts[3][3], 0xFB)

        btn_pkts = build_inphic_button_packets({1: "triple-click", 2: "right-click", 4: "forward", 5: "backward", 6: "dpi-cycle"})
        self.assertEqual(len(btn_pkts), 8)  # 6 slots + 0x08 CPI alt + 0x11 normal scroll wheel guard
        # Slot 1 (0x01) hard-guarded to Left Click (0x01) even if caller passes triple-click!
        self.assertEqual(btn_pkts[0][:4], bytes([0x07, 0x10, 0x01, 0x01]))
        # Slot 2 (0x03) -> Right Click (0x03)
        self.assertEqual(btn_pkts[1][:4], bytes([0x07, 0x10, 0x03, 0x03]))
        # Slot 4 (0x05 Side Forward) -> Forward (0x05), Slot 5 (0x04 Side Backward) -> Backward (0x04)
        self.assertEqual(btn_pkts[3][:4], bytes([0x07, 0x10, 0x05, 0x05]))
        self.assertEqual(btn_pkts[4][:4], bytes([0x07, 0x10, 0x04, 0x04]))

        # 2. Verify passive CPI button interrupt 0x06 decoding (press vs 0x80 release)
        ev = decode_inphic_interrupt(bytes([0x06, 0xF6, 0x02]))
        self.assertEqual(ev, InphicCpiEvent(stage=3, button_mask=0xF6))
        self.assertIsNone(decode_inphic_interrupt(bytes([0x06, 0xF6, 0x80])))

        # 3. Verify InphicW1State round-trip
        st = InphicW1State(stages_cpi=[800, 1200, 1800, 2400], current_stage=3, light_mode=0x16)
        st2 = InphicW1State.from_json_dict(st.to_json_dict())
        self.assertEqual(st2.stages_cpi, [800, 1200, 1800, 2400])
        self.assertEqual(st2.current_stage, 3)
        self.assertEqual(st2.light_mode, 0x16)
        self.assertIn("inphic_w1", MODEL_CAPABILITIES)
        self.assertIn("delux_m618xsd", MODEL_CAPABILITIES)

        # 4. Verify Inphic W1 Virtual Side-Wheel Chord (Hold Forward + Main Wheel vs Tap Forward)
        mouse_emitted: list[list[tuple[int, int, int]]] = []
        combos_emitted: list[list[int]] = []
        daemon = SmartMouseDaemon()
        daemon.virtual.emit_mouse = lambda evs, sync=True: mouse_emitted.append(list(evs))  # type: ignore[method-assign]
        daemon.virtual.emit_key_combo = lambda codes: combos_emitted.append(list(codes))  # type: ignore[method-assign]

        # Configure Forward button on active default profile as Virtual Side-Wheel for Tab Switching
        prof = daemon._active_prof_cached
        prof.bindings["forward"] = ActionSpec(
            kind="gesture_4way",
            tap={"kind": "passthrough"},
            wheel_up={"kind": "key_combo", "combo": "Ctrl+Shift+Tab"},
            wheel_down={"kind": "key_combo", "combo": "Ctrl+Tab"},
        )

        # Case A: Single tap Forward -> emits native BTN_EXTRA click!
        daemon._process_batch_safe([(EV_KEY, BTN_EXTRA, 1), (EV_SYN, 0, 0)])
        daemon._process_batch_safe([(EV_KEY, BTN_EXTRA, 0), (EV_SYN, 0, 0)])
        flat_mouse = [(t, c, v) for b in mouse_emitted for (t, c, v) in b]
        self.assertIn((EV_KEY, BTN_EXTRA, 1), flat_mouse)
        self.assertIn((EV_KEY, BTN_EXTRA, 0), flat_mouse)

        # Case B: Hold Forward + Scroll Wheel Down -> emits Ctrl+Tab without native Forward click!
        mouse_emitted.clear()
        combos_emitted.clear()
        daemon._process_batch_safe([(EV_KEY, BTN_EXTRA, 1), (EV_SYN, 0, 0)])
        daemon._process_batch_safe([(EV_REL, REL_WHEEL, -1), (EV_SYN, 0, 0)])
        daemon._process_batch_safe([(EV_KEY, BTN_EXTRA, 0), (EV_SYN, 0, 0)])
        self.assertEqual(combos_emitted, [[29, 15]])  # Ctrl+Tab
        flat_mouse_chord = [(t, c, v) for b in mouse_emitted for (t, c, v) in b]
        self.assertNotIn((EV_KEY, BTN_EXTRA, 1), flat_mouse_chord)

    def test_live_hardware_readonly_session(self) -> None:
        from omni_mouse.hardware.session import SessionError

        nodes = list_m618xsd_nodes()
        if not nodes or not nodes[0].accessible:
            self.skipTest("M618XSD node not currently accessible")
        try:
            with M618XSDSession() as session:
                dpi = session.read_dpi()
                light = session.read_lighting()
                poll = session.read_polling()
                self.assertIn(poll.hz, (125, 250, 500, 1000))
                self.assertTrue(400 <= dpi.dpi[0] <= 4000)
                self.assertTrue(1 <= light.brightness <= 8)
        except SessionError as exc:
            self.skipTest(f"M618XSD wireless mouse currently in sleep mode: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
