"""Localhost threaded HTTP/JSON bridge between the WebKit2 Control Center UI and Delux M618XSD / Inphic W1 hardware & daemon."""

from __future__ import annotations

import glob
import http.server
import json
import mimetypes
import os
import secrets
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
from typing import Any

from ..config.profiles import (
    ACTION_PRESETS,
    BINDABLE_INPUTS,
    CONFIG_DIR,
    CONFIG_PATH,
    DriverConfig,
    load_config,
    save_config,
)
from ..daemon.engine import query_daemon
from ..daemon.linux_input import list_supported_mouse_evdev
from ..daemon.window_tracker import ActiveWindowTracker
from ..hardware import protocol as hp
from ..hardware.inphic_w1 import (
    INPHIC_ACTION_CODE_BY_KEY,
    INPHIC_BACKUP_PATH,
    INPHIC_FIRMWARE_ACTIONS,
    INPHIC_LIGHT_CODE_BY_KEY,
    INPHIC_LIGHT_MODES,
    INPHIC_SLOTS,
    InphicW1Session,
    InphicW1State,
    list_inphic_w1_nodes,
    load_inphic_state,
    save_inphic_state,
    snap_inphic_cpi,
)
from ..hardware.session import M618XSDSession, SessionError, list_m618xsd_nodes

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FACTORY_BACKUP_PATH = os.path.join(PROJECT_ROOT, "factory_backup.json")
USER_BACKUP_PATH = os.path.join(CONFIG_DIR, "user_hardware_backup.json")
HW_CACHE_PATH = os.path.join(CONFIG_DIR, "last_hw_cache.json")

BINDABLE_INPUTS_W1: dict[str, str] = {
    "forward": "前进侧键 (Forward)",
    "backward": "后退侧键 (Backward)",
    "middle": "滚轮中键 (Middle Click)",
}

MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    "delux_m618xsd": {
        "has_thumb_wheel": True,
        "has_battery": True,
        "has_polling": True,
        "has_debounce": True,
        "has_sleep": True,
        "has_rgb_color": True,
        "has_hw_combos": True,
        "dpi_stages": 5,
        "dpi_min": 400,
        "dpi_max": 4000,
        "dpi_step": 50,
    },
    "inphic_w1": {
        "has_thumb_wheel": False,
        "has_battery": False,
        "has_polling": False,
        "has_debounce": False,
        "has_sleep": False,
        "has_rgb_color": False,
        "has_hw_combos": False,
        "dpi_stages": 4,
        "dpi_min": 400,
        "dpi_max": 4800,
        "dpi_step": 400,
    },
}


class StudioBackendState:
    """Thread-safe coordinator for multi-mouse hardware reads/writes and smart daemon IPC."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.token = secrets.token_hex(16)
        self.window_tracker = ActiveWindowTracker(cache_ttl=0.08)

        cfg = load_config(CONFIG_PATH)
        self.selected_model: str = cfg.preferred_model if cfg.preferred_model in ("auto", "delux_m618xsd", "inphic_w1") else "auto"

        # Delux M618XSD state objects
        self._dpi_obj: hp.DpiSettings = hp.DpiSettings()
        self._light_obj: hp.LightingSettings = hp.LightingSettings()
        self._poll_obj: hp.PollingRate = hp.PollingRate()
        self._btn_obj: hp.ButtonSettings = hp.ButtonSettings()
        self._prof_obj: hp.ProfileSettings = hp.ProfileSettings()

        for snap_path in (USER_BACKUP_PATH, FACTORY_BACKUP_PATH):
            if os.path.exists(snap_path):
                try:
                    with open(snap_path, encoding="utf-8") as fh:
                        snap = json.load(fh)
                    if "0x04" in snap:
                        self._dpi_obj = hp.DpiSettings.from_bytes(bytes.fromhex(snap["0x04"]))
                    if "0x05" in snap:
                        self._light_obj = hp.LightingSettings.from_bytes(bytes.fromhex(snap["0x05"]))
                    if "0x06" in snap:
                        self._poll_obj = hp.PollingRate.from_bytes(bytes.fromhex(snap["0x06"]))
                    if "0x08" in snap:
                        self._btn_obj = hp.ButtonSettings.from_bytes(bytes.fromhex(snap["0x08"]))
                    break
                except Exception:
                    pass

        cached_bat: dict[str, Any] = {
            "percent": None,
            "state": 1,
            "state_label": "等待唤醒读取",
            "charging": False,
        }
        cached_fw = "--"
        if os.path.exists(HW_CACHE_PATH):
            try:
                with open(HW_CACHE_PATH, encoding="utf-8") as fh:
                    prev = json.load(fh)
                if isinstance(prev.get("battery"), dict) and isinstance(prev["battery"].get("percent"), int):
                    cached_bat = prev["battery"]
                if prev.get("firmware"):
                    cached_fw = str(prev["firmware"])
            except Exception:
                pass

        self._delux_cache: dict[str, Any] = {
            "model": "delux_m618xsd",
            "model_name": "DELUX M618XSD",
            "connection_type": "wireless_24g",
            "capabilities": MODEL_CAPABILITIES["delux_m618xsd"],
            "connected": False,
            "sleeping": False,
            "node": "",
            "firmware": cached_fw,
            "error": "",
            "last_sync": 0.0,
            "profile_settings": {"current": self._prof_obj.current, "maximum": self._prof_obj.maximum},
            "dpi": self._dpi_obj.to_dict(),
            "lighting": self._light_obj.to_dict(),
            "polling": self._poll_obj.to_dict(),
            "buttons": self._serialize_delux_buttons(self._btn_obj),
            "battery": cached_bat,
        }

        # Inphic W1 state
        self._inphic_state: InphicW1State = load_inphic_state()

    def resolve_active_model(self) -> str:
        if self.selected_model in ("delux_m618xsd", "inphic_w1"):
            return self.selected_model
        if list_m618xsd_nodes():
            return "delux_m618xsd"
        if list_inphic_w1_nodes():
            return "inphic_w1"
        ev_nodes = list_supported_mouse_evdev()
        if ev_nodes:
            return ev_nodes[0].model_key
        st = query_daemon("status")
        if st and st.get("device_model") in ("delux_m618xsd", "inphic_w1"):
            return str(st["device_model"])
        return "delux_m618xsd"

    def _build_inphic_hw_dict(self, error: str = "") -> dict[str, Any]:
        self._inphic_state = load_inphic_state()
        inodes = list_inphic_w1_nodes()
        ev_nodes = [n for n in list_supported_mouse_evdev() if n.model_key == "inphic_w1"]
        connected = bool(inodes or ev_nodes)
        node_str = inodes[0].path if inodes else (ev_nodes[0].path if ev_nodes else "")
        if not connected and not error:
            error = "未检测到英菲克 Inphic W1 (30fa:1701)，请确认 USB 已连接。"
        elif connected and not inodes and not error:
            error = "已识别到 Inphic W1 USB 鼠标，但尚未获取 /dev/hidraw* 访问权限，请运行 udev 权限安装脚本。"
        return {
            "model": "inphic_w1",
            "model_selection": self.selected_model,
            "model_name": "INPHIC W1",
            "connection_type": "wired_usb",
            "capabilities": MODEL_CAPABILITIES["inphic_w1"],
            "connected": connected,
            "sleeping": False,
            "node": node_str,
            "firmware": "Instant A704 (USB)",
            "error": error,
            "last_sync": time.time(),
            "profile_settings": {"current": 1, "maximum": 1},
            "dpi": self._inphic_state.to_dpi_dict(),
            "lighting": self._inphic_state.to_lighting_dict(),
            "polling": {"hz": 125},
            "buttons": self._inphic_state.to_buttons_dict(),
            "battery": {
                "percent": 100,
                "state": 2,
                "state_label": "USB 有线直连供电",
                "charging": False,
                "wired": True,
            },
        }

    def get_current_hardware_view(self) -> dict[str, Any]:
        model = self.resolve_active_model()
        if model == "inphic_w1":
            return self._build_inphic_hw_dict()
        out = dict(self._delux_cache)
        out["model_selection"] = self.selected_model
        return out

    def select_device_model(self, model_sel: str) -> dict[str, Any]:
        if model_sel not in ("auto", "delux_m618xsd", "inphic_w1"):
            raise ValueError(f"不支持的设备选择: {model_sel}")
        with self.lock:
            self.selected_model = model_sel
            cfg = load_config(CONFIG_PATH)
            cfg.preferred_model = model_sel
            save_config(cfg, CONFIG_PATH)
        query_daemon("reload")
        self.refresh_hardware(fast=True)
        return self.full_state_payload()

    def refresh_hardware(self, profile: int | None = None, fast: bool = False) -> dict[str, Any]:
        model = self.resolve_active_model()
        if model == "inphic_w1":
            with self.lock:
                inodes = list_inphic_w1_nodes()
                err = ""
                if inodes and not fast and self._inphic_state.user_configured:
                    try:
                        with InphicW1Session(node=inodes[0]) as sess:
                            sess.write_dpi(self._inphic_state)
                            sess.write_lighting(self._inphic_state)
                    except Exception as exc:
                        err = str(exc)
                return self._build_inphic_hw_dict(error=err)

        with self.lock:
            nodes = list_m618xsd_nodes()
            if not nodes:
                self._delux_cache["connected"] = False
                self._delux_cache["sleeping"] = False
                self._delux_cache["error"] = "未检测到多彩 M618XSD (1d57:fa60)，请插入 2.4G 接收器或切换至当前已连接鼠标。"
                out = dict(self._delux_cache)
                out["model_selection"] = self.selected_model
                return out
            tries = 0 if fast else 1
            g_delay = 0.14 if fast else 0.18
            s_delay = 0.04 if fast else 0.05
            try:
                with M618XSDSession(grant_delay=g_delay, settle=s_delay) as sess:
                    prof_set = sess.read_profile_settings(retries=tries)
                    target_prof = profile if profile in (1, 2) else prof_set.current
                    dpi = sess.read_dpi(profile=target_prof, retries=tries)
                    light = sess.read_lighting(retries=tries)
                    poll = sess.read_polling(retries=tries)
                    btns = sess.read_buttons(profile=target_prof, retries=tries)
                    fw = sess.read_firmware_version(retries=tries)
                    bat = sess.read_battery(timeout=0.15)

                    self._prof_obj = prof_set
                    self._dpi_obj = dpi
                    self._light_obj = light
                    self._poll_obj = poll
                    self._btn_obj = btns

                    bat_dict = self._delux_cache.get("battery") or {
                        "percent": None,
                        "state": 1,
                        "state_label": "无线在线",
                        "charging": False,
                    }
                    if bat is not None:
                        bat_dict = {
                            "percent": bat.percent,
                            "state": bat.state,
                            "state_label": bat.state_label,
                            "charging": bat.charging,
                        }

                    self._delux_cache = {
                        "model": "delux_m618xsd",
                        "model_name": "DELUX M618XSD",
                        "connection_type": "wireless_24g",
                        "capabilities": MODEL_CAPABILITIES["delux_m618xsd"],
                        "connected": True,
                        "sleeping": False,
                        "node": sess.node.path,
                        "firmware": fw,
                        "error": "",
                        "last_sync": time.time(),
                        "profile_settings": {
                            "current": prof_set.current,
                            "maximum": prof_set.maximum,
                        },
                        "dpi": dpi.to_dict(),
                        "lighting": light.to_dict(),
                        "polling": poll.to_dict(),
                        "buttons": self._serialize_delux_buttons(btns),
                        "battery": bat_dict,
                    }
                    try:
                        os.makedirs(CONFIG_DIR, exist_ok=True)
                        with open(HW_CACHE_PATH, "w", encoding="utf-8") as fh:
                            json.dump({"firmware": fw, "battery": bat_dict, "ts": time.time()}, fh)
                    except OSError:
                        pass
            except (SessionError, OSError, ValueError) as exc:
                self._delux_cache["connected"] = bool(nodes)
                self._delux_cache["sleeping"] = bool(nodes)
                self._delux_cache["node"] = nodes[0].path if nodes else ""
                self._delux_cache["error"] = "" if fast else str(exc)
            out = dict(self._delux_cache)
            out["model_selection"] = self.selected_model
            return out

    def _serialize_delux_buttons(self, btns: hp.ButtonSettings) -> dict[str, Any]:
        slots_out = []
        for slot_num, label in hp.M618XSD_SLOTS.items():
            sl = btns.slot(slot_num)
            combo_str = ""
            if sl.action == 0x11:
                mods = [name.capitalize() for name, bit in hp.HID_MODIFIERS.items() if sl.modifiers & bit]
                from ..hardware.keymap import hid_key_name

                mods.append(hid_key_name(sl.usage))
                combo_str = "+".join(mods)
            slots_out.append(
                {
                    "slot": slot_num,
                    "label": label,
                    "action_code": sl.action,
                    "action_key": sl.action_key,
                    "combo": combo_str,
                    "description": sl.describe(),
                }
            )
        return {"profile": btns.profile, "slots": slots_out}

    def apply_dpi(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = self.resolve_active_model()
        if model == "inphic_w1":
            with self.lock:
                st = load_inphic_state()
                st.user_configured = True
                st.current_stage = max(1, min(4, int(payload.get("current_stage", st.current_stage))))
                for item in payload.get("stages") or []:
                    idx = int(item.get("stage", 0)) - 1
                    if 0 <= idx < 4:
                        st.stages_enabled[idx] = bool(item.get("enabled", True))
                        st.stages_cpi[idx] = snap_inphic_cpi(int(item.get("dpi", st.stages_cpi[idx])))
                        rgb = item.get("rgb")
                        if isinstance(rgb, list) and len(rgb) == 3:
                            st.stages_rgb[idx] = [max(0, min(255, int(c))) for c in rgb]
                if not any(st.stages_enabled):
                    st.stages_enabled[st.current_stage - 1] = True
                if not st.stages_enabled[st.current_stage - 1]:
                    for idx in range(4):
                        if st.stages_enabled[idx]:
                            st.current_stage = idx + 1
                            break
                with InphicW1Session() as sess:
                    sess.write_dpi(st)
                save_inphic_state(st)
                self._inphic_state = st
                return {"ok": True, "dpi": st.to_dpi_dict()}

        with self.lock:
            dpi = self._dpi_obj
            current_stage = int(payload.get("current_stage", dpi.current_stage))
            dpi.current_stage = max(1, min(5, current_stage))
            stages = payload.get("stages") or []
            for item in stages:
                st_num = int(item.get("stage", 0))
                if 1 <= st_num <= 5:
                    dpi.set_stage_enabled(st_num, bool(item.get("enabled", True)))
                    dpi.set_stage_dpi(st_num, int(item.get("dpi", dpi.dpi[st_num - 1])))
                    rgb = item.get("rgb")
                    if isinstance(rgb, list) and len(rgb) == 3:
                        dpi.colors[st_num - 1] = (
                            max(0, min(255, int(rgb[0]))),
                            max(0, min(255, int(rgb[1]))),
                            max(0, min(255, int(rgb[2]))),
                        )
            if not dpi.stage_enabled(dpi.current_stage):
                for st_num in range(1, 6):
                    if dpi.stage_enabled(st_num):
                        dpi.current_stage = st_num
                        break
            with M618XSDSession() as sess:
                sess.write_dpi(dpi, refresh_lighting=self._light_obj)
            self._delux_cache["dpi"] = dpi.to_dict()
            self._delux_cache["error"] = ""
            return {"ok": True, "dpi": self._delux_cache["dpi"]}

    def apply_polling(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.resolve_active_model() == "inphic_w1":
            return {"ok": True, "polling": {"hz": 125}}
        with self.lock:
            hz = int(payload.get("hz", 250))
            self._poll_obj.hz = hz
            with M618XSDSession() as sess:
                sess.write_polling(self._poll_obj)
            self._delux_cache["polling"] = self._poll_obj.to_dict()
            self._delux_cache["error"] = ""
            return {"ok": True, "polling": self._delux_cache["polling"]}

    def apply_lighting(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = self.resolve_active_model()
        if model == "inphic_w1":
            with self.lock:
                st = load_inphic_state()
                st.user_configured = True
                if "mode" in payload and int(payload["mode"]) in INPHIC_LIGHT_MODES:
                    st.light_mode = int(payload["mode"])
                elif "mode_key" in payload and payload["mode_key"] in INPHIC_LIGHT_CODE_BY_KEY:
                    st.light_mode = INPHIC_LIGHT_CODE_BY_KEY[payload["mode_key"]]
                if "rgb" in payload and isinstance(payload["rgb"], list) and len(payload["rgb"]) == 3:
                    st.light_rgb = [max(0, min(255, int(c))) for c in payload["rgb"]]
                with InphicW1Session() as sess:
                    sess.write_lighting(st)
                save_inphic_state(st)
                self._inphic_state = st
                return {"ok": True, "lighting": st.to_lighting_dict()}

        with self.lock:
            lt = self._light_obj
            if "mode" in payload:
                lt.mode = int(payload["mode"])
            elif "mode_key" in payload and payload["mode_key"] in hp.LIGHT_CODE_BY_KEY:
                lt.mode = hp.LIGHT_CODE_BY_KEY[payload["mode_key"]]
            if "brightness" in payload:
                lt.brightness = max(1, min(8, int(payload["brightness"])))
            if "led_speed" in payload:
                lt.led_speed = max(1, min(5, int(payload["led_speed"])))
            if "rgb" in payload and isinstance(payload["rgb"], list) and len(payload["rgb"]) == 3:
                r, g, b = payload["rgb"]
                lt.rgb = (max(0, min(255, int(r))), max(0, min(255, int(g))), max(0, min(255, int(b))))
            if "light_sleep_minutes" in payload:
                lt.light_sleep_minutes = max(0.5, min(30.0, float(payload["light_sleep_minutes"])))
            if "deep_sleep_minutes" in payload:
                lt.deep_sleep_minutes = max(1, min(60, int(payload["deep_sleep_minutes"])))
            if "debounce_ms" in payload:
                lt.debounce_ms = max(4, min(50, int(round(int(payload["debounce_ms"]) / 2) * 2)))
            with M618XSDSession() as sess:
                sess.write_lighting(lt)
            self._delux_cache["lighting"] = lt.to_dict()
            self._delux_cache["error"] = ""
            return {"ok": True, "lighting": self._delux_cache["lighting"]}

    def apply_onboard_buttons(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = self.resolve_active_model()
        if model == "inphic_w1":
            with self.lock:
                st = load_inphic_state()
                st.user_configured = True
                for item in payload.get("slots", []):
                    slot_num = int(item.get("slot", 0))
                    act_key = str(item.get("action_key", ""))
                    if slot_num in INPHIC_SLOTS and act_key in INPHIC_ACTION_CODE_BY_KEY:
                        if slot_num == 1:
                            continue  # Protect primary left-click
                        st.button_actions[slot_num] = act_key
                with InphicW1Session() as sess:
                    sess.write_buttons(st)
                save_inphic_state(st)
                self._inphic_state = st
                return {"ok": True, "buttons": st.to_buttons_dict()}

        with self.lock:
            btns = self._btn_obj
            for item in payload.get("slots", []):
                slot_num = int(item.get("slot", 0))
                if slot_num not in hp.M618XSD_SLOTS:
                    continue
                act_key = str(item.get("action_key", ""))
                combo = str(item.get("combo", "")).strip()
                if act_key == "keyboard-key" and combo:
                    btns.set_slot(slot_num, hp.ButtonSlot.from_combo(combo))
                elif act_key in hp.ACTION_CODE_BY_KEY:
                    btns.set_slot(slot_num, hp.ButtonSlot(action=hp.ACTION_CODE_BY_KEY[act_key]))
            with M618XSDSession() as sess:
                if "active_onboard_profile" in payload:
                    target_p = max(1, min(2, int(payload["active_onboard_profile"])))
                    self._prof_obj.current = target_p
                    sess.write_profile_settings(self._prof_obj)
                    time.sleep(0.08)
                sess.write_buttons(btns)
            self._delux_cache["buttons"] = self._serialize_delux_buttons(btns)
            self._delux_cache["profile_settings"] = {
                "current": self._prof_obj.current,
                "maximum": self._prof_obj.maximum,
            }
            return {"ok": True, "buttons": self._delux_cache["buttons"]}

    def backup_hardware(self) -> dict[str, Any]:
        model = self.resolve_active_model()
        if model == "inphic_w1":
            with self.lock:
                st = load_inphic_state()
                save_inphic_state(st, path=INPHIC_BACKUP_PATH)
                return {"ok": True, "path": INPHIC_BACKUP_PATH}

        with self.lock:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            dump: dict[str, str] = {}
            with M618XSDSession() as sess:
                for rid in (hp.RID_DPI, hp.RID_LIGHT, hp.RID_POLL, hp.RID_BUTTONS, hp.RID_PROFILE_SET):
                    raw = sess.read_raw_report(rid)
                    dump[f"0x{rid:02x}"] = raw.hex()
            with open(USER_BACKUP_PATH, "w", encoding="utf-8") as fh:
                json.dump(dump, fh, indent=2)
            return {"ok": True, "path": USER_BACKUP_PATH}

    def restore_hardware(self, source: str = "factory") -> dict[str, Any]:
        model = self.resolve_active_model()
        if model == "inphic_w1":
            with self.lock:
                if source == "factory":
                    st = InphicW1State(user_configured=True)
                else:
                    if not os.path.exists(INPHIC_BACKUP_PATH):
                        raise RuntimeError(f"未找到 Inphic W1 备份文件: {INPHIC_BACKUP_PATH}")
                    st = load_inphic_state(path=INPHIC_BACKUP_PATH)
                    st.user_configured = True
                with InphicW1Session() as sess:
                    sess.write_all(st)
                save_inphic_state(st)
                self._inphic_state = st
            return {"ok": True, "restored": ["0x07"], "hardware": self._build_inphic_hw_dict()}

        path = FACTORY_BACKUP_PATH if source == "factory" else USER_BACKUP_PATH
        if not os.path.exists(path):
            raise RuntimeError(f"未找到备份文件: {path}")
        with self.lock:
            with M618XSDSession() as sess:
                restored = sess.restore_backup_file(path)
        hw = self.refresh_hardware()
        return {"ok": True, "restored": restored, "hardware": hw}

    def daemon_status(self) -> dict[str, Any]:
        st = query_daemon("status")
        if st is not None:
            return st
        win = self.window_tracker.current_window()
        cfg = load_config(CONFIG_PATH)
        prof = cfg.resolve_profile(win.app_id, win.wm_class, win.title)
        return {
            "ok": False,
            "pid": None,
            "daemon_enabled": cfg.daemon_enabled,
            "per_app_enabled": cfg.per_app_enabled,
            "device_path": "",
            "device_name": "",
            "device_model": "",
            "grabbed": False,
            "window": {
                "app_id": win.app_id,
                "wm_class": win.wm_class,
                "title": win.title,
                "backend": win.backend,
                "label": win.display_label(),
            },
            "active_profile": {"id": prof.id, "name": prof.name},
            "logs": ["守护进程当前未运行 — 点击右上角「启动守护进程」即可激活应用自动切换与多功能手势。"],
        }

    def control_daemon(self, action: str) -> dict[str, Any]:
        if action == "reload":
            res = query_daemon("reload")
            if res is not None:
                return res
        if action in ("start", "restart"):
            res = subprocess.run(
                ["systemctl", "--user", "restart", "delux-m618xsd-daemon.service"],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                daemon_bin = os.path.join(PROJECT_ROOT, "m618xsd-daemon")
                subprocess.Popen(
                    [sys.executable, daemon_bin],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            time.sleep(0.55)
        elif action == "stop":
            subprocess.run(
                ["systemctl", "--user", "stop", "delux-m618xsd-daemon.service"],
                capture_output=True,
                text=True,
                check=False,
            )
            query_daemon("stop")
            time.sleep(0.25)
        return self.daemon_status()

    def save_driver_config(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = DriverConfig.from_dict(data)
        cfg.preferred_model = self.selected_model
        save_config(cfg, CONFIG_PATH)
        st = query_daemon("reload")
        return {
            "ok": True,
            "config": cfg.to_dict(),
            "daemon": st or self.daemon_status(),
        }

    def list_discoverable_apps(self) -> dict[str, Any]:
        """Return currently running windows + installed desktop apps for 1-click selection."""
        running: list[dict[str, str]] = []
        seen_running: set[str] = set()

        conn = self.window_tracker._ensure_a11y_bus()
        if conn is not None:
            try:
                from gi.repository import Gio, GLib  # type: ignore

                apps = conn.call_sync(
                    "org.a11y.atspi.Registry",
                    "/org/a11y/atspi/accessible/root",
                    "org.a11y.atspi.Accessible",
                    "GetChildren",
                    None,
                    GLib.VariantType("(a(so))"),
                    Gio.DBusCallFlags.NONE,
                    250,
                    None,
                ).unpack()[0]
                for app_sender, app_path in apps:
                    if not app_sender or not app_path:
                        continue
                    try:
                        app_name = str(
                            conn.call_sync(
                                app_sender,
                                app_path,
                                "org.freedesktop.DBus.Properties",
                                "Get",
                                GLib.Variant("(ss)", ("org.a11y.atspi.Accessible", "Name")),
                                GLib.VariantType("(v)"),
                                Gio.DBusCallFlags.NONE,
                                80,
                                None,
                            ).unpack()[0]
                            or ""
                        ).strip()
                        if not app_name or app_name.lower() in ("gnome-shell", "mutter-x11-frames"):
                            continue
                        app_id, wm_class = self.window_tracker._resolve_a11y_sender_proc(conn, app_sender, app_name)
                        token = (app_id.split()[0] if app_id else wm_class).replace(".desktop", "").strip().lower()
                        if not token or token in ("delux-m618xsd-studio", "m618xsd-studio", "python3"):
                            continue
                        if token not in seen_running:
                            seen_running.add(token)
                            running.append({"name": wm_class or app_name, "pattern": token})
                    except Exception:
                        continue
            except Exception:
                pass

        installed_map: dict[str, dict[str, str]] = {}
        for droot in ("/usr/share/applications", os.path.expanduser("~/.local/share/applications")):
            for path in sorted(glob.glob(os.path.join(droot, "*.desktop"))):
                try:
                    with open(path, encoding="utf-8", errors="ignore") as fh:
                        txt = fh.read()
                except OSError:
                    continue
                name_zh, name_en, exec_cmd, nodisp, app_type = "", "", "", False, ""
                in_entry = False
                for line in txt.splitlines():
                    s = line.strip()
                    if s.startswith("["):
                        in_entry = s == "[Desktop Entry]"
                        continue
                    if not in_entry or "=" not in s:
                        continue
                    k, v = s.split("=", 1)
                    if k == "NoDisplay" and v.strip().lower() == "true":
                        nodisp = True
                    elif k == "Type":
                        app_type = v.strip()
                    elif k == "Name":
                        name_en = v.strip()
                    elif k in ("Name[zh_CN]", "Name[zh]"):
                        name_zh = v.strip()
                    elif k == "Exec":
                        exec_cmd = v.strip()
                if nodisp or app_type != "Application" or not exec_cmd:
                    continue
                first = exec_cmd.split()[0].strip('"')
                bin_name = os.path.basename(first)
                if bin_name in ("env", "sh", "bash", "python3"):
                    rest = [p for p in exec_cmd.split()[1:] if "=" not in p and not p.startswith("-")]
                    if rest:
                        bin_name = os.path.basename(rest[0].strip('"'))
                bin_clean = bin_name.lower()
                for suffix in ("-stable", "-bin"):
                    if bin_clean.endswith(suffix):
                        bin_clean = bin_clean[: -len(suffix)]
                disp = name_zh or name_en
                if disp and bin_clean and bin_clean not in ("m618xsd-studio",):
                    installed_map[bin_clean] = {"name": disp, "pattern": bin_clean}

        installed = sorted(installed_map.values(), key=lambda x: x["name"].lower())
        return {"ok": True, "running": running, "installed": installed}

    def pick_window_now(self) -> dict[str, Any]:
        st = query_daemon("pick_window")
        if st and st.get("window"):
            return {"ok": True, "window": st["window"]}
        win = self.window_tracker.current_window(force=True)
        return {
            "ok": True,
            "window": {
                "app_id": win.app_id,
                "wm_class": win.wm_class,
                "title": win.title,
                "backend": win.backend,
                "label": win.display_label(),
            },
        }

    def _meta_for_model(self, model: str) -> dict[str, Any]:
        if model == "inphic_w1":
            return {
                "bindable_inputs": BINDABLE_INPUTS_W1,
                "action_presets": [
                    {"id": pid, "label": lbl, "spec": spec} for pid, lbl, spec in ACTION_PRESETS
                ],
                "light_modes": [
                    {"code": code, "key": key, "label": label}
                    for code, (key, label) in INPHIC_LIGHT_MODES.items()
                ],
                "firmware_actions": [
                    {"code": code, "key": key, "label": label}
                    for code, (key, label) in INPHIC_FIRMWARE_ACTIONS.items()
                ],
                "poll_rates": [125],
                "has_factory_backup": True,
                "has_user_backup": os.path.exists(INPHIC_BACKUP_PATH),
            }
        return {
            "bindable_inputs": BINDABLE_INPUTS,
            "action_presets": [
                {"id": pid, "label": lbl, "spec": spec} for pid, lbl, spec in ACTION_PRESETS
            ],
            "light_modes": [
                {"code": code, "key": key, "label": label}
                for code, (key, label) in hp.LIGHT_MODES.items()
            ],
            "firmware_actions": [
                {"code": code, "key": key, "label": label}
                for code, (key, label) in hp.FIRMWARE_ACTIONS.items()
                if code != 0x00
            ],
            "poll_rates": list(hp.POLL_RATES),
            "has_factory_backup": os.path.exists(FACTORY_BACKUP_PATH),
            "has_user_backup": os.path.exists(USER_BACKUP_PATH),
        }

    def full_state_payload(self) -> dict[str, Any]:
        cfg = load_config(CONFIG_PATH)
        hw = self.get_current_hardware_view()
        model = str(hw.get("model", "delux_m618xsd"))
        return {
            "hardware": hw,
            "daemon": self.daemon_status(),
            "config": cfg.to_dict(),
            "meta": self._meta_for_model(model),
        }


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_studio_server(backend: StudioBackendState) -> tuple[_ThreadedHTTPServer, str]:
    """Start loopback HTTP server on 127.0.0.1:0 and return (server, entry_url)."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _check_auth(self, parsed: urllib.parse.ParseResult) -> bool:
            hdr = self.headers.get("X-Studio-Token", "")
            if hdr == backend.token:
                return True
            qs = urllib.parse.parse_qs(parsed.query)
            return qs.get("token", [""])[0] == backend.token

        def _serve_file(self, base_dir: str, rel_path: str) -> None:
            safe_path = os.path.normpath(os.path.join(base_dir, rel_path.lstrip("/")))
            if not safe_path.startswith(os.path.normpath(base_dir)) or not os.path.isfile(safe_path):
                self.send_error(404)
                return
            ctype, _ = mimetypes.guess_type(safe_path)
            with open(safe_path, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype or "application/octet-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
                if not self._check_auth(parsed):
                    self.send_error(403)
                    return
                backend.refresh_hardware(fast=True)
                self._serve_file(WEB_DIR, "index.html")
                return
            if path.startswith("/web/"):
                self._serve_file(WEB_DIR, path[5:])
                return
            if path.startswith("/assets/"):
                self._serve_file(ASSETS_DIR, path[8:])
                return
            if not self._check_auth(parsed):
                self._send_json({"ok": False, "error": "Unauthorized"}, status=403)
                return
            if path == "/api/state":
                self._send_json(backend.full_state_payload())
                return
            if path == "/api/apps":
                self._send_json(backend.list_discoverable_apps())
                return
            if path == "/api/telemetry":
                daemon_st = backend.daemon_status()
                hw_view = backend.get_current_hardware_view()
                if hw_view.get("model") == "delux_m618xsd":
                    d_bat = daemon_st.get("battery") if isinstance(daemon_st, dict) else None
                    if isinstance(d_bat, dict) and isinstance(d_bat.get("percent"), int):
                        backend._delux_cache["battery"] = d_bat
                        hw_view["battery"] = d_bat
                self._send_json(
                    {
                        "ok": True,
                        "daemon": daemon_st,
                        "hardware": {
                            "model": hw_view.get("model"),
                            "model_selection": hw_view.get("model_selection"),
                            "connected": hw_view.get("connected", False),
                            "sleeping": hw_view.get("sleeping", False),
                            "node": hw_view.get("node", ""),
                            "firmware": hw_view.get("firmware", "--"),
                            "error": hw_view.get("error", ""),
                            "battery": hw_view.get("battery"),
                            "dpi": hw_view.get("dpi"),
                            "lighting": hw_view.get("lighting"),
                            "polling": hw_view.get("polling"),
                        },
                    }
                )
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if not self._check_auth(parsed):
                self._send_json({"ok": False, "error": "Unauthorized"}, status=403)
                return
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                payload = {}

            path = parsed.path
            try:
                if path == "/api/device/select":
                    state_out = backend.select_device_model(str(payload.get("model", "auto")))
                    self._send_json({"ok": True, **state_out})
                elif path == "/api/hardware/refresh":
                    hw = backend.refresh_hardware(
                        profile=payload.get("profile"),
                        fast=bool(payload.get("fast", False)),
                    )
                    self._send_json({"ok": not bool(hw.get("error")), "hardware": hw})
                elif path == "/api/hardware/dpi":
                    self._send_json(backend.apply_dpi(payload))
                elif path == "/api/hardware/polling":
                    self._send_json(backend.apply_polling(payload))
                elif path == "/api/hardware/lighting":
                    self._send_json(backend.apply_lighting(payload))
                elif path == "/api/hardware/buttons":
                    self._send_json(backend.apply_onboard_buttons(payload))
                elif path == "/api/hardware/backup":
                    self._send_json(backend.backup_hardware())
                elif path == "/api/hardware/restore":
                    self._send_json(backend.restore_hardware(source=str(payload.get("source", "factory"))))
                elif path == "/api/config/save":
                    self._send_json(backend.save_driver_config(payload))
                elif path == "/api/daemon/control":
                    st = backend.control_daemon(str(payload.get("action", "restart")))
                    self._send_json({"ok": True, "daemon": st})
                elif path == "/api/daemon/pick_window":
                    self._send_json(backend.pick_window_now())
                else:
                    self._send_json({"ok": False, "error": f"Unknown endpoint: {path}"}, status=404)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)

    server = _ThreadedHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/?token={backend.token}"
    return server, url
