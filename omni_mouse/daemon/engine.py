"""Smart userspace remapping, 4-way mouse gesture, chord & per-app daemon for M618XSD."""

from __future__ import annotations

import collections
import errno
import json
import os
import select
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..config.profiles import (
    CONFIG_DIR,
    CONFIG_PATH,
    IPC_SOCKET_PATH,
    ActionSpec,
    AppProfile,
    DriverConfig,
    load_config,
)
from ..hardware import protocol as hp
from ..hardware.inphic_w1 import (
    InphicW1Session,
    decode_inphic_interrupt,
    list_inphic_w1_nodes,
    load_inphic_state,
    save_inphic_state,
)
from ..hardware.keymap import parse_combo_to_evdev, resolve_evdev_key
from ..hardware.session import list_m618xsd_nodes
from .linux_input import (
    BTN_EXTRA,
    BTN_LEFT,
    BTN_MIDDLE,
    BTN_RIGHT,
    BTN_SIDE,
    EV_KEY,
    EV_REL,
    EV_SYN,
    REL_HWHEEL,
    REL_HWHEEL_HI_RES,
    REL_WHEEL,
    REL_WHEEL_HI_RES,
    REL_X,
    REL_Y,
    PhysicalMouseReader,
    VirtualInputPair,
    find_supported_mouse_evdev,
)
from .window_tracker import ActiveWindowTracker, WindowInfo

BUTTON_CODE_TO_SLOT = {
    BTN_EXTRA: "forward",
    BTN_SIDE: "backward",
    BTN_MIDDLE: "middle",
}

SLOT_TO_BUTTON_CODE = {v: k for k, v in BUTTON_CODE_TO_SLOT.items()}
HW_CACHE_PATH = os.path.join(CONFIG_DIR, "last_hw_cache.json")


@dataclass
class ActiveGestureState:
    slot: str
    btn_code: int
    spec: ActionSpec
    dx: float = 0.0
    dy: float = 0.0
    triggered: bool = False
    started_at: float = field(default_factory=time.monotonic)


class SmartMouseDaemon:
    """Intercepts physical M618XSD mouse inputs and applies per-app smart actions & gestures."""

    def __init__(self, config_path: str = CONFIG_PATH, ipc_path: str = IPC_SOCKET_PATH):
        self.config_path = config_path
        self.ipc_path = ipc_path
        self.config: DriverConfig = load_config(config_path)
        self._config_mtime: float = self._stat_config()
        # Keep window_tracker off the evdev cursor hot-path via background watcher thread
        self.window_tracker = ActiveWindowTracker(cache_ttl=0.18)
        self.virtual = VirtualInputPair()
        self.reader: PhysicalMouseReader | None = None
        self.device_name: str = ""
        self.device_path: str = ""
        self.device_model: str = ""
        self._hidraw_fd: int | None = None
        self._hidraw_path: str = ""
        self._hidraw_model: str = ""
        self.running = False

        # Runtime states
        self._sniper_scale: float | None = None
        self._sniper_btn: int | None = None
        self._passthrough_held: set[int] = set()
        self._gesture: ActiveGestureState | None = None
        self._frac_x: float = 0.0
        self._frac_y: float = 0.0
        self._hwheel_accum: int = 0
        self._recent_logs: collections.deque[str] = collections.deque(maxlen=40)
        self._last_window = WindowInfo()
        self._active_prof_cached: AppProfile = self.config.global_profile
        self._last_profile_name = self.config.global_profile.name
        self._battery_cache: dict[str, Any] | None = self._load_cached_battery()
        self._last_bat_persist: float = 0.0
        self._last_mouse_event_ts: float = 0.0
        self._focus_wake = threading.Event()
        self._ipc_sock: socket.socket | None = None

    def _load_cached_battery(self) -> dict[str, Any] | None:
        try:
            if os.path.exists(HW_CACHE_PATH):
                with open(HW_CACHE_PATH, encoding="utf-8") as fh:
                    data = json.load(fh)
                bat = data.get("battery")
                if isinstance(bat, dict) and isinstance(bat.get("percent"), int):
                    return bat
        except Exception:
            pass
        return None

    def _persist_battery(self, bat: dict[str, Any]) -> None:
        now = time.time()
        if now - self._last_bat_persist < 10.0:
            return
        self._last_bat_persist = now
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            prev: dict[str, Any] = {}
            if os.path.exists(HW_CACHE_PATH):
                try:
                    with open(HW_CACHE_PATH, encoding="utf-8") as fh:
                        prev = json.load(fh)
                except Exception:
                    prev = {}
            prev["battery"] = bat
            prev["ts"] = now
            with open(HW_CACHE_PATH, "w", encoding="utf-8") as fh:
                json.dump(prev, fh)
        except OSError:
            pass

    def _log(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._recent_logs.appendleft(f"[{stamp}] {msg}")

    def _stat_config(self) -> float:
        try:
            return os.path.getmtime(self.config_path)
        except OSError:
            return 0.0

    def reload_if_changed(self, force: bool = False) -> bool:
        mtime = self._stat_config()
        if force or mtime != self._config_mtime:
            self.config = load_config(self.config_path)
            self._config_mtime = mtime
            win = self._last_window
            self._active_prof_cached = self.config.resolve_profile(win.app_id, win.wm_class, win.title)
            self._log("已热重载配置文件")
            return True
        return False

    def _refresh_focus_once(self, force: bool = False) -> tuple[WindowInfo, AppProfile]:
        win = self.window_tracker.current_window(force=force)
        prof = self.config.resolve_profile(win.app_id, win.wm_class, win.title)
        self._active_prof_cached = prof
        if win != self._last_window or prof.name != self._last_profile_name:
            self._last_window = win
            if prof.name != self._last_profile_name:
                self._log(f"切换配置 -> 「{prof.name}」 ({win.display_label()})")
                self._last_profile_name = prof.name
        return win, prof

    def _focus_watcher_loop(self) -> None:
        """Event-driven focus resolver: 0% CPU when mouse is idle, <1ms wakeup on mouse motion."""
        try:
            self._refresh_focus_once(force=False)
        except Exception:
            pass
        while self.running:
            self._focus_wake.wait(timeout=60.0)
            self._focus_wake.clear()
            while self.running:
                if self.config.daemon_enabled and self.config.per_app_enabled:
                    try:
                        self._refresh_focus_once(force=False)
                    except Exception:
                        pass
                if time.monotonic() - self._last_mouse_event_ts > 1.6:
                    break
                time.sleep(0.30)

    def _open_ipc(self) -> None:
        os.makedirs(os.path.dirname(self.ipc_path), exist_ok=True)
        if os.path.exists(self.ipc_path):
            try:
                os.unlink(self.ipc_path)
            except OSError:
                pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self.ipc_path)
        os.chmod(self.ipc_path, 0o600)
        sock.listen(8)
        sock.setblocking(False)
        self._ipc_sock = sock

    def _close_ipc(self) -> None:
        if self._ipc_sock is not None:
            try:
                self._ipc_sock.close()
            except OSError:
                pass
            self._ipc_sock = None
        if os.path.exists(self.ipc_path):
            try:
                os.unlink(self.ipc_path)
            except OSError:
                pass

    def _handle_ipc_client(self) -> None:
        if self._ipc_sock is None:
            return
        try:
            conn, _ = self._ipc_sock.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(0.2)
            try:
                raw = conn.recv(4096).decode("utf-8", errors="replace").strip()
                req = json.loads(raw) if raw else {"cmd": "status"}
            except Exception:
                req = {"cmd": "status"}
            cmd = req.get("cmd", "status")
            if cmd == "reload":
                self.reload_if_changed(force=True)
            elif cmd == "stop":
                self.running = False

            if cmd == "pick_window":
                win, prof = self._refresh_focus_once(force=True)
            else:
                win = self._last_window
                prof = self._active_prof_cached

            reply = {
                "ok": True,
                "pid": os.getpid(),
                "daemon_enabled": self.config.daemon_enabled,
                "per_app_enabled": self.config.per_app_enabled,
                "device_path": self.device_path,
                "device_name": self.device_name,
                "device_model": self.device_model,
                "grabbed": bool(self.reader and self.reader.grabbed),
                "window": {
                    "app_id": win.app_id,
                    "wm_class": win.wm_class,
                    "title": win.title,
                    "backend": win.backend,
                    "label": win.display_label(),
                },
                "active_profile": {"id": prof.id, "name": prof.name},
                "battery": self._battery_cache,
                "logs": list(self._recent_logs),
            }
            try:
                conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                pass

    def _execute_action(self, spec: ActionSpec, native_btn: int | None = None, source_label: str = "") -> None:
        if spec.kind == "disabled":
            self._log(f"{source_label}: 已拦截禁用")
            return
        if spec.kind == "passthrough":
            if native_btn is not None:
                self.virtual.emit_mouse([(EV_KEY, native_btn, 1)], sync=True)
                time.sleep(0.012)
                self.virtual.emit_mouse([(EV_KEY, native_btn, 0)], sync=True)
            return
        if spec.kind == "key_combo" and spec.combo:
            try:
                codes = parse_combo_to_evdev(spec.combo)
                self.virtual.emit_key_combo(codes)
                self._log(f"{source_label} -> 快捷键 {spec.combo}")
            except Exception as exc:
                self._log(f"快捷键错误 ({spec.combo}): {exc}")
            return
        if spec.kind == "media" and spec.media:
            try:
                code = resolve_evdev_key(spec.media)
                self.virtual.emit_key_combo([code])
                self._log(f"{source_label} -> 媒体键 {spec.media}")
            except Exception as exc:
                self._log(f"媒体键错误: {exc}")
            return
        if spec.kind == "zoom":
            mode = spec.zoom_mode or "auto"
            if mode == "auto":
                win_tag = f"{self._last_window.app_id} {self._last_window.wm_class}".lower()
                key_zoom_apps = (
                    "loupe",
                    "图像查看器",
                    "图片查看器",
                    "papers",
                    "evince",
                    "文档查看器",
                    "okular",
                    "eog",
                    "shotwell",
                    "gthumb",
                )
                mode = "keys" if any(k in win_tag for k in key_zoom_apps) else "wheel"
            self.virtual.emit_zoom(spec.direction, mode=mode)
            via = "Ctrl+=" if (mode == "keys" and spec.direction > 0) else ("Ctrl+-" if mode == "keys" else "Ctrl+滚轮")
            self._log(f"{source_label} -> 画面{'放大' if spec.direction > 0 else '缩小'} ({via})")
            return
        if spec.kind == "scroll":
            self.virtual.emit_scroll(spec.axis, spec.step)
            self._log(f"{source_label} -> 滚动 {spec.axis}:{spec.step:+d}")
            return
        if spec.kind == "command" and spec.command:
            try:
                subprocess.Popen(
                    ["/bin/sh", "-c", spec.command],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self._log(f"{source_label} -> 执行命令: {spec.command}")
            except Exception as exc:
                self._log(f"命令执行失败: {exc}")
            return
        if spec.kind == "macro" and spec.macro_steps:
            steps = list(spec.macro_steps)

            def _run_macro() -> None:
                for idx, st in enumerate(steps):
                    combo = str(st.get("combo", "")).strip()
                    delay_ms = max(0, min(5000, int(st.get("delay_ms", 35))))
                    if combo:
                        try:
                            codes = parse_combo_to_evdev(combo)
                            self.virtual.emit_key_combo(codes)
                        except Exception as exc:
                            self._log(f"宏步骤#{idx+1}错误 ({combo}): {exc}")
                    if delay_ms > 0 and idx + 1 < len(steps):
                        time.sleep(delay_ms / 1000.0)

            threading.Thread(target=_run_macro, daemon=True).start()
            self._log(f"{source_label} -> 执行宏序列 ({len(steps)}步)")

    def _validate_gesture_alive(self, now: float) -> None:
        """Guarantee a dropped wireless release event can NEVER freeze cursor or wheel."""
        if self._gesture is None:
            return
        age = now - self._gesture.started_at
        if age > 2.2:
            self._gesture = None
            return
        if age > 0.30 and self.reader is not None and not self.reader.is_button_physically_held(self._gesture.btn_code):
            self._gesture = None

    def _process_batch(self, events: list[tuple[int, int, int]]) -> None:
        prof = self._active_prof_cached
        out_mouse: list[tuple[int, int, int]] = []
        now = time.monotonic()

        self._validate_gesture_alive(now)

        # Combine pointer scales
        scale = prof.pointer_scale
        if self._sniper_scale is not None:
            scale *= self._sniper_scale

        # Check if thumbwheel is passthrough in current profile
        thumb_up_spec = prof.get_binding("thumb_up")
        thumb_down_spec = prof.get_binding("thumb_down")
        thumb_is_passthrough = (
            thumb_up_spec.kind == "passthrough" and thumb_down_spec.kind == "passthrough"
        )

        for ev_type, code, value in events:
            if ev_type == EV_SYN:
                if out_mouse:
                    self.virtual.emit_mouse(out_mouse, sync=True)
                    out_mouse.clear()
                continue

            if ev_type == EV_REL:
                if code in (REL_X, REL_Y):
                    # If a 4-way gesture button is currently held, accumulate gesture movement!
                    if self._gesture is not None:
                        if code == REL_X:
                            self._gesture.dx += value
                        else:
                            self._gesture.dy += value
                        thresh = max(20, self._gesture.spec.gesture_threshold)
                        if not self._gesture.triggered:
                            adx, ady = abs(self._gesture.dx), abs(self._gesture.dy)
                            if max(adx, ady) >= thresh:
                                self._gesture.triggered = True
                                if adx >= ady:
                                    sub_dict = self._gesture.spec.right if self._gesture.dx > 0 else self._gesture.spec.left
                                    dir_lbl = "右滑手势" if self._gesture.dx > 0 else "左滑手势"
                                else:
                                    sub_dict = self._gesture.spec.down if self._gesture.dy > 0 else self._gesture.spec.up
                                    dir_lbl = "下滑手势" if self._gesture.dy > 0 else "上滑手势"
                                if sub_dict:
                                    self._execute_action(
                                        ActionSpec.from_dict(sub_dict),
                                        source_label=f"{self._gesture.slot}·{dir_lbl}",
                                    )
                            elif (now - self._gesture.started_at) < 0.45:
                                # Only freeze cursor briefly (<0.45s) while aiming an un-triggered slide gesture
                                continue

                    if abs(scale - 1.0) < 1e-3:
                        out_mouse.append((EV_REL, code, value))
                    else:
                        if code == REL_X:
                            total = self._frac_x + value * scale
                            iv = int(total)
                            self._frac_x = total - iv
                        else:
                            total = self._frac_y + value * scale
                            iv = int(total)
                            self._frac_y = total - iv
                        if iv != 0:
                            out_mouse.append((EV_REL, code, iv))

                elif code in (REL_WHEEL, REL_WHEEL_HI_RES):
                    if self._gesture is not None:
                        if code == REL_WHEEL and value != 0:
                            sub_dict = self._gesture.spec.wheel_up if value > 0 else self._gesture.spec.wheel_down
                            if sub_dict:
                                self._gesture.triggered = True
                                self._gesture.started_at = now  # Keep chord alive while actively scrolling
                                self._execute_action(
                                    ActionSpec.from_dict(sub_dict),
                                    source_label=f"{self._gesture.slot}+滚轮{'上' if value > 0 else '下'}",
                                )
                        continue
                    v = -value if prof.wheel_invert else value
                    out_mouse.append((EV_REL, code, v))

                elif code in (REL_HWHEEL, REL_HWHEEL_HI_RES):
                    v = -value if prof.thumb_invert else value
                    if thumb_is_passthrough:
                        scaled = int(round(v * prof.thumb_speed))
                        if scaled == 0 and v != 0:
                            scaled = 1 if v > 0 else -1
                        out_mouse.append((EV_REL, code, scaled))
                    else:
                        if code == REL_HWHEEL and v != 0:
                            self._hwheel_accum = 0
                            spec = thumb_up_spec if v < 0 else thumb_down_spec
                            lbl = "拇指滚轮上拨" if v < 0 else "拇指滚轮下拨"
                            steps = max(1, abs(v))
                            for _ in range(steps):
                                self._execute_action(spec, source_label=lbl)
                        elif code == REL_HWHEEL_HI_RES and v != 0:
                            self._hwheel_accum += v
                            while abs(self._hwheel_accum) >= 120:
                                sign = 1 if self._hwheel_accum > 0 else -1
                                self._hwheel_accum -= sign * 120

            elif ev_type == EV_KEY:
                if code in (BTN_LEFT, BTN_RIGHT):
                    if value == 1 and self._gesture is not None:
                        self._gesture = None
                    out_mouse.append((EV_KEY, code, value))
                    continue

                slot = BUTTON_CODE_TO_SLOT.get(code)
                if slot is None:
                    out_mouse.append((EV_KEY, code, value))
                    continue

                # Release handling
                if value == 0:
                    if code in self._passthrough_held:
                        self._passthrough_held.discard(code)
                        out_mouse.append((EV_KEY, code, 0))
                        continue
                    if self._sniper_btn == code:
                        self._sniper_btn = None
                        self._sniper_scale = None
                        self._log(f"{slot}: 退出微操模式")
                        continue
                    if self._gesture is not None and self._gesture.btn_code == code:
                        gest = self._gesture
                        self._gesture = None
                        if not gest.triggered:
                            tap_spec = ActionSpec.from_dict(gest.spec.tap or {"kind": "passthrough"})
                            self._execute_action(tap_spec, native_btn=code, source_label=f"{slot}·单击")
                        continue
                    continue

                # Press handling (value == 1)
                if value == 1:
                    spec = prof.get_binding(slot)
                    if spec.kind == "passthrough":
                        self._passthrough_held.add(code)
                        out_mouse.append((EV_KEY, code, 1))
                    elif spec.kind == "sniper_dpi":
                        self._sniper_btn = code
                        self._sniper_scale = max(0.1, min(3.0, spec.scale))
                        self._log(f"{slot}: 开启微操灵敏度 ({self._sniper_scale:.2f}x)")
                    elif spec.kind == "gesture_4way":
                        self._gesture = ActiveGestureState(slot=slot, btn_code=code, spec=spec, started_at=now)
                    else:
                        self._execute_action(spec, native_btn=code, source_label=slot)

        if out_mouse:
            self.virtual.emit_mouse(out_mouse, sync=True)

    def _process_batch_safe(self, batch: list[tuple[int, int, int]]) -> None:
        try:
            self._process_batch(batch)
        except Exception as exc:
            self._gesture = None
            self._sniper_scale = None
            self._log(f"输入处理异常已自动恢复直通: {exc}")
            fallback = [
                (t, c, v)
                for (t, c, v) in batch
                if (t == EV_REL) or (t == EV_KEY and c in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA))
            ]
            if fallback:
                self.virtual.emit_mouse(fallback, sync=True)

    def _sync_passive_hidraw(self) -> None:
        """Open config hidraw strictly O_RDONLY to receive passive Report 0x03 (M618XSD) or 0x06 (Inphic W1) events."""
        if self._hidraw_fd is not None and os.path.exists(self._hidraw_path):
            if not self.device_model or self._hidraw_model == self.device_model:
                return
            self._close_passive_hidraw()

        target = ""
        target_model = ""
        if self.device_model == "inphic_w1":
            inodes = list_inphic_w1_nodes()
            if inodes:
                target = inodes[0].path
                target_model = "inphic_w1"
        elif self.device_model == "delux_m618xsd":
            mnodes = list_m618xsd_nodes()
            if mnodes:
                target = mnodes[0].path
                target_model = "delux_m618xsd"
        else:
            mnodes = list_m618xsd_nodes()
            if mnodes:
                target = mnodes[0].path
                target_model = "delux_m618xsd"
            else:
                inodes = list_inphic_w1_nodes()
                if inodes:
                    target = inodes[0].path
                    target_model = "inphic_w1"

        if not target:
            return
        try:
            self._hidraw_fd = os.open(target, os.O_RDONLY | os.O_NONBLOCK)
            self._hidraw_path = target
            self._hidraw_model = target_model
        except OSError:
            self._hidraw_fd = None
            self._hidraw_path = ""
            self._hidraw_model = ""

    def _close_passive_hidraw(self) -> None:
        if self._hidraw_fd is not None:
            try:
                os.close(self._hidraw_fd)
            except OSError:
                pass
            self._hidraw_fd = None
            self._hidraw_path = ""
            self._hidraw_model = ""

    def _drain_passive_hidraw(self) -> None:
        if self._hidraw_fd is None:
            return
        for _ in range(16):
            try:
                pkt = os.read(self._hidraw_fd, 64)
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno == errno.EAGAIN:
                    break
                self._close_passive_hidraw()
                break
            if not pkt:
                break
            if self._hidraw_model == "inphic_w1":
                iev = decode_inphic_interrupt(pkt)
                if iev is not None:
                    st = load_inphic_state()
                    if st.current_stage != iev.stage:
                        st.current_stage = iev.stage
                        try:
                            save_inphic_state(st)
                        except OSError:
                            pass
                    cpi_val = st.stages_cpi[iev.stage - 1] if 1 <= iev.stage <= len(st.stages_cpi) else 1200
                    self._log(f"Inphic W1 物理 CPI 键切换 -> 第 {iev.stage} 档 ({cpi_val} CPI)")
                continue

            ev = hp.decode_interrupt_event(pkt)
            if isinstance(ev, hp.BatteryEvent):
                bat_dict = {
                    "percent": ev.percent,
                    "state": ev.state,
                    "state_label": ev.state_label,
                    "charging": ev.charging,
                }
                self._battery_cache = bat_dict
                self._persist_battery(bat_dict)
            elif isinstance(ev, hp.DpiCycleEvent):
                self._log(f"硬件 DPI 键切换 -> 第 {ev.stage} 档")

    def _reapply_inphic_sram_if_saved(self) -> None:
        st = load_inphic_state()
        if not st.user_configured:
            return
        try:
            with InphicW1Session() as sess:
                sess.write_dpi(st)
                sess.write_lighting(st)
                if st.buttons_configured:
                    sess.write_buttons(st)
            self._log("已向 Inphic W1 自动恢复保存的 CPI 与灯光参数")
        except Exception as exc:
            self._log(f"恢复 Inphic W1 参数提示: {exc}")

    def _sync_grab_state(self) -> None:
        if not self.config.daemon_enabled:
            if self.reader is not None:
                self.reader.close()
                self.reader = None
                self.device_path = ""
                self.device_model = ""
                self._gesture = None
                self._log("智能增强层已暂停（恢复纯硬件直通模式）")
            return

        if self.reader is not None and not os.path.exists(self.device_path):
            self.reader.close()
            self.reader = None
            self.device_path = ""
            self.device_model = ""
            self._gesture = None

        pref = None if self.config.preferred_model == "auto" else self.config.preferred_model
        if self.reader is not None and pref and self.device_model and self.device_model != pref:
            cand = find_supported_mouse_evdev(preferred_model=pref)
            if cand is not None and cand.path != self.device_path:
                self.reader.close()
                self.reader = None
                self.device_path = ""
                self.device_model = ""
                self._gesture = None

        if self.reader is None:
            node = find_supported_mouse_evdev(preferred_model=pref)
            if node is not None:
                reader = PhysicalMouseReader(node.path)
                try:
                    reader.open_and_grab()
                    self.reader = reader
                    self.device_path = node.path
                    self.device_name = node.name
                    self.device_model = node.model_key
                    self._gesture = None
                    model_title = "Inphic W1" if node.model_key == "inphic_w1" else "Delux M618XSD"
                    self._log(f"已接管 {model_title} 输入: {node.name} ({node.path})")
                    if node.model_key == "inphic_w1":
                        threading.Thread(target=self._reapply_inphic_sram_if_saved, daemon=True).start()
                except OSError as exc:
                    reader.close()
                    self._log(f"接管鼠标失败: {exc}")

    def run(self) -> int:
        self.running = True

        def _stop_handler(_signum: int, _frame: Any) -> None:
            self.running = False

        signal.signal(signal.SIGINT, _stop_handler)
        signal.signal(signal.SIGTERM, _stop_handler)

        self._open_ipc()
        try:
            self.virtual.open()
        except OSError as exc:
            self._log(f"无法打开 /dev/uinput: {exc}")
            self._close_ipc()
            raise RuntimeError(f"无法打开 /dev/uinput ({exc})，请先安装 udev 权限规则。") from exc

        focus_thread = threading.Thread(target=self._focus_watcher_loop, daemon=True)
        focus_thread.start()

        self._log("Delux M618XSD 智能守护引擎已启动")
        last_housekeep = 0.0

        try:
            while self.running:
                now = time.monotonic()
                if now - last_housekeep >= 2.0:
                    last_housekeep = now
                    self.reload_if_changed()
                    self._sync_grab_state()
                    self._sync_passive_hidraw()
                    self._validate_gesture_alive(now)

                watch_fds: list[int] = []
                if self._ipc_sock is not None:
                    watch_fds.append(self._ipc_sock.fileno())
                if self.reader is not None and self.reader.fd is not None:
                    watch_fds.append(self.reader.fd)
                if self._hidraw_fd is not None:
                    watch_fds.append(self._hidraw_fd)

                # Sleep up to 4.0s when idle (0.00% CPU); poll 0.25s only while gesture state is active or awaiting device
                sel_timeout = 0.25 if (self._gesture is not None or self.reader is None) else 4.0
                ready, _, _ = select.select(watch_fds, [], [], sel_timeout)
                if self._ipc_sock is not None and self._ipc_sock.fileno() in ready:
                    self._handle_ipc_client()

                if self._hidraw_fd is not None and self._hidraw_fd in ready:
                    self._drain_passive_hidraw()

                if self.reader is not None and self.reader.fd is not None and self.reader.fd in ready:
                    try:
                        batch = self.reader.read_events()
                        if batch:
                            ev_now = time.monotonic()
                            if self.config.per_app_enabled and (ev_now - self._last_mouse_event_ts > 0.35):
                                self._focus_wake.set()
                            self._last_mouse_event_ts = ev_now
                            self._process_batch_safe(batch)
                    except OSError:
                        self._log(f"设备已断开 ({self.device_path})，等待重连...")
                        self.reader.close()
                        self.reader = None
                        self.device_path = ""
                        self._gesture = None
        finally:
            self.running = False
            self._focus_wake.set()
            if self.reader is not None:
                self.reader.close()
                self.reader = None
            self._close_passive_hidraw()
            self.virtual.close()
            self._close_ipc()
        return 0


def query_daemon(cmd: str = "status", ipc_path: str = IPC_SOCKET_PATH) -> dict[str, Any] | None:
    if not os.path.exists(ipc_path):
        return None
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(0.35)
    try:
        sock.connect(ipc_path)
        sock.sendall(json.dumps({"cmd": cmd}).encode("utf-8"))
        data = sock.recv(16384).decode("utf-8", errors="replace")
        return json.loads(data)
    except Exception:
        return None
    finally:
        sock.close()
