"""Hardware protocol & session manager for Inphic W1 (Instant A704 / A725 USB Gaming Mouse).

Supports USB IDs 30fa:1701, 30fa:1440, and 18f8:1286 via HID Feature Report 0x07 (8 bytes)
on Interface 1, plus passive Input Report 0x06 decoding for physical CPI button stage tracking.
Because the Instant A704 controller stores parameters in volatile SRAM (write-only), state is
persisted locally in ~/.config/delux-m618xsd/inphic_w1_hw.json and re-applied automatically.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from ..config.profiles import CONFIG_DIR
from .hidraw import HidrawDevice, HidrawNode, enumerate_hidraw

INPHIC_VIDS = (0x30FA, 0x18F8)
INPHIC_SUPPORTED_PIDS = {0x1701, 0x1440, 0x1286}
RID_INPHIC_CFG = 0x07
RID_INPHIC_EVT = 0x06

INPHIC_STATE_PATH = os.path.join(CONFIG_DIR, "inphic_w1_hw.json")
INPHIC_BACKUP_PATH = os.path.join(CONFIG_DIR, "inphic_w1_backup.json")

# 8 hardware LED modes supported by Instant A704 (Command 0x13, sub-header 0x7F)
INPHIC_LIGHT_MODES: dict[int, tuple[str, str]] = {
    0x17: ("off", "关闭背光"),
    0x16: ("static", "常亮模式"),
    0x12: ("breathe_4s", "标准呼吸 (4秒周期)"),
    0x10: ("breathe_6s", "慢速呼吸 (6秒周期)"),
    0x11: ("breathe_5s", "舒缓呼吸 (5秒周期)"),
    0x13: ("breathe_3s", "快速呼吸 (3秒周期)"),
    0x14: ("pulse_2s", "高频律动 (2秒周期)"),
    0x15: ("pulse_1s", "疾速脉冲 (1秒周期)"),
}

INPHIC_LIGHT_CODE_BY_KEY = {k: code for code, (k, _) in INPHIC_LIGHT_MODES.items()}

# Hardware button register codes (Command 0x10: 07 10 BT AT 00 00 00 00)
# Verified against Instant A704 / A704F (30fa:1701) firmware specification:
# BT: 0x01=LMB, 0x02=MMB, 0x03=RMB, 0x05=Side Forward, 0x04=Side Backward, 0x06/0x08=Top CPI
# AT: 0x01=Left, 0x02=Middle, 0x03=Right, 0x04=Backward, 0x05=Forward, 0x06=DPI Cycle,
#     0x07=Show Desktop, 0x08=Double Click, 0x09=Fire, 0x0B=DPI+, 0x0C=DPI-
INPHIC_SLOTS: dict[int, tuple[int, str, str]] = {
    1: (0x01, "左键 (Left Click)", "left-click"),
    2: (0x03, "右键 (Right Click)", "right-click"),
    3: (0x02, "滚轮中键 (Middle Click)", "middle-click"),
    4: (0x05, "前进侧键 (Forward)", "forward"),
    5: (0x04, "后退侧键 (Backward)", "backward"),
    6: (0x06, "顶部 CPI 键 (CPI Cycle)", "dpi-cycle"),
}

INPHIC_FIRMWARE_ACTIONS: dict[int, tuple[str, str]] = {
    0x01: ("left-click", "左键点击 (Left Click)"),
    0x03: ("right-click", "右键菜单 (Right Click)"),
    0x02: ("middle-click", "中键点击 (Middle Click)"),
    0x05: ("forward", "侧键 · 前进 (Forward)"),
    0x04: ("backward", "侧键 · 后退 (Backward)"),
    0x08: ("double-click", "左键双击 (Double Click)"),
    0x09: ("triple-click", "连发火力键 (Rapid Fire)"),
    0x06: ("dpi-cycle", "CPI 档位循环切换"),
    0x0B: ("dpi-up", "CPI 加档 (CPI +)"),
    0x0C: ("dpi-down", "CPI 减档 (CPI -)"),
    0x07: ("show-desktop", "显示桌面 (Show Desktop)"),
}

INPHIC_ACTION_CODE_BY_KEY = {k: code for code, (k, _) in INPHIC_FIRMWARE_ACTIONS.items()}

DEFAULT_STAGE_COLORS: list[list[int]] = [
    [0, 210, 255],
    [37, 99, 235],
    [139, 92, 246],
    [245, 158, 11],
]


@dataclass
class InphicCpiEvent:
    stage: int
    button_mask: int


def is_inphic_config_node(node: HidrawNode) -> bool:
    return node.vid in INPHIC_VIDS and RID_INPHIC_CFG in node.features


def list_inphic_w1_nodes() -> list[HidrawNode]:
    nodes = [
        node
        for node in enumerate_hidraw()
        if node.vid in INPHIC_VIDS and (node.pid in INPHIC_SUPPORTED_PIDS or is_inphic_config_node(node))
    ]
    return sorted(nodes, key=lambda n: (not is_inphic_config_node(n), n.path))


def find_inphic_w1_node(node_path: str | None = None) -> HidrawNode:
    nodes = list_inphic_w1_nodes()
    if node_path:
        matched = [n for n in nodes if n.path == node_path]
        if not matched:
            raise RuntimeError(f"未找到指定的 Inphic W1 设备节点: {node_path}")
        nodes = matched
    for candidate in nodes:
        if is_inphic_config_node(candidate):
            return candidate
    raise RuntimeError("未检测到英菲克 Inphic W1 有线鼠标配置通道 (30fa:1701)，请确认 USB 已连接且 udev 权限已生效。")


def snap_inphic_cpi(val: int) -> int:
    """Snap CPI to Instant A704 hardware step (200..3000 CPI in 200-CPI increments, nibble 1..15)."""
    nibble = max(1, min(15, int(round(int(val) / 200.0))))
    return nibble * 200


def build_inphic_lighting_packet(mode_code: int) -> bytes:
    if mode_code not in INPHIC_LIGHT_MODES:
        mode_code = 0x12
    return bytes([RID_INPHIC_CFG, 0x13, 0x7F, mode_code & 0xFF, 0x00, 0x00, 0x00, 0x00])


def build_inphic_dpi_packets(
    stages_cpi: list[int],
    enabled_flags: list[bool],
    current_stage: int,
) -> list[bytes]:
    """Build the 4 x 8-byte Report 0x07 CPI configuration packets for Instant A704."""
    active_idx = max(0, min(3, int(current_stage) - 1))
    mask = 0
    for idx in range(4):
        if idx < len(enabled_flags) and enabled_flags[idx]:
            mask |= 1 << idx
    if mask == 0:
        mask = 1 << active_idx
    if not (mask & (1 << active_idx)):
        for idx in range(4):
            if mask & (1 << idx):
                active_idx = idx
                break

    packets: list[bytes] = []
    for idx in range(4):
        cpi = snap_inphic_cpi(stages_cpi[idx] if idx < len(stages_cpi) else (idx + 2) * 400)
        nibble = max(1, min(15, cpi // 200))
        b0 = active_idx & 0x03
        b1 = ((nibble & 0x0F) << 4) | (0x08 + idx)
        b2 = mask & 0x0F
        packets.append(bytes([RID_INPHIC_CFG, 0x09, b0, b1, b2, 0x00, 0x00, 0x00]))
    return packets


def build_inphic_button_packets(slot_actions: dict[int, str]) -> list[bytes]:
    """Build 8-byte Report 0x07 hardware button assignment packets for Instant A704."""
    packets: list[bytes] = []
    for slot_num, (btn_hex, _lbl, default_key) in INPHIC_SLOTS.items():
        # Hard guard: Slot 1 (LMB) always stays left-click so primary clicking can never be locked out
        act_key = "left-click" if slot_num == 1 else slot_actions.get(slot_num, default_key)
        act_code = INPHIC_ACTION_CODE_BY_KEY.get(act_key, INPHIC_ACTION_CODE_BY_KEY[default_key])
        packets.append(bytes([RID_INPHIC_CFG, 0x10, btn_hex, act_code, 0x00, 0x00, 0x00, 0x00]))
        if slot_num == 6:
            # Instant A704/A704F variants wire top CPI button to 0x06 or 0x08
            packets.append(bytes([RID_INPHIC_CFG, 0x10, 0x08, act_code, 0x00, 0x00, 0x00, 0x00]))
    # Ensure wheel stays in normal scroll mode (0x00)
    packets.append(bytes([RID_INPHIC_CFG, 0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]))
    return packets


def decode_inphic_interrupt(pkt: bytes | bytearray) -> InphicCpiEvent | None:
    if len(pkt) >= 3 and pkt[0] == RID_INPHIC_EVT:
        # pkt[2] == 0x80 indicates button release on Instant A704; only decode press (0x00..0x03)
        if int(pkt[2]) & 0x80:
            return None
        stage = (int(pkt[2]) & 0x03) + 1
        return InphicCpiEvent(stage=stage, button_mask=int(pkt[1]))
    return None


@dataclass
class InphicW1State:
    user_configured: bool = False
    buttons_configured: bool = False
    current_stage: int = 2
    stages_cpi: list[int] = field(default_factory=lambda: [800, 1200, 1600, 2400])
    stages_enabled: list[bool] = field(default_factory=lambda: [True, True, True, True])
    stages_rgb: list[list[int]] = field(default_factory=lambda: [list(c) for c in DEFAULT_STAGE_COLORS])
    light_mode: int = 0x12
    light_rgb: list[int] = field(default_factory=lambda: [0, 200, 255])
    button_actions: dict[int, str] = field(
        default_factory=lambda: {slot: default_key for slot, (_bh, _lb, default_key) in INPHIC_SLOTS.items()}
    )

    def to_dpi_dict(self) -> dict[str, Any]:
        return {
            "profile": 1,
            "current_stage": max(1, min(4, self.current_stage)),
            "stages": [
                {
                    "stage": idx + 1,
                    "enabled": bool(self.stages_enabled[idx]),
                    "dpi": snap_inphic_cpi(self.stages_cpi[idx]),
                    "rgb": list(self.stages_rgb[idx]) if idx < len(self.stages_rgb) else [0, 200, 255],
                }
                for idx in range(4)
            ],
        }

    def to_lighting_dict(self) -> dict[str, Any]:
        key, label = INPHIC_LIGHT_MODES.get(self.light_mode, ("breathe_4s", "标准呼吸 (4秒周期)"))
        # Map speed preview for 3D viewer animation
        speed_map = {0x10: 1, 0x11: 2, 0x12: 3, 0x13: 4, 0x14: 5, 0x15: 5, 0x16: 3, 0x17: 0}
        return {
            "mode": self.light_mode,
            "mode_key": key,
            "mode_label": label,
            "brightness": 8 if self.light_mode != 0x17 else 0,
            "led_speed": speed_map.get(self.light_mode, 3),
            "rgb": list(self.light_rgb),
            "light_sleep_minutes": 0,
            "deep_sleep_minutes": 0,
            "debounce_ms": 8,
        }

    def to_buttons_dict(self) -> dict[str, Any]:
        slots_out = []
        for slot_num, (_btn_hex, label, default_key) in INPHIC_SLOTS.items():
            act_key = self.button_actions.get(slot_num, default_key)
            act_code = INPHIC_ACTION_CODE_BY_KEY.get(act_key, INPHIC_ACTION_CODE_BY_KEY[default_key])
            _, desc = INPHIC_FIRMWARE_ACTIONS.get(act_code, (act_key, act_key))
            slots_out.append(
                {
                    "slot": slot_num,
                    "label": label,
                    "action_code": act_code,
                    "action_key": act_key,
                    "combo": "",
                    "description": desc,
                }
            )
        return {"profile": 1, "slots": slots_out}

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "user_configured": self.user_configured,
            "buttons_configured": self.buttons_configured,
            "current_stage": self.current_stage,
            "stages_cpi": [snap_inphic_cpi(x) for x in self.stages_cpi[:4]],
            "stages_enabled": [bool(x) for x in self.stages_enabled[:4]],
            "stages_rgb": [list(c) for c in self.stages_rgb[:4]],
            "light_mode": self.light_mode,
            "light_rgb": list(self.light_rgb[:3]),
            "button_actions": {str(k): v for k, v in self.button_actions.items()},
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "InphicW1State":
        st = cls()
        st.user_configured = bool(data.get("user_configured", False))
        st.buttons_configured = bool(data.get("buttons_configured", False))
        st.current_stage = max(1, min(4, int(data.get("current_stage", 2))))
        raw_cpi = data.get("stages_cpi")
        if isinstance(raw_cpi, list) and len(raw_cpi) == 4:
            st.stages_cpi = [snap_inphic_cpi(int(x)) for x in raw_cpi]
        raw_en = data.get("stages_enabled")
        if isinstance(raw_en, list) and len(raw_en) == 4:
            st.stages_enabled = [bool(x) for x in raw_en]
        raw_rgb = data.get("stages_rgb")
        if isinstance(raw_rgb, list) and len(raw_rgb) == 4:
            st.stages_rgb = [[max(0, min(255, int(c))) for c in row[:3]] for row in raw_rgb]
        lm = int(data.get("light_mode", 0x12))
        st.light_mode = lm if lm in INPHIC_LIGHT_MODES else 0x12
        lrgb = data.get("light_rgb")
        if isinstance(lrgb, list) and len(lrgb) == 3:
            st.light_rgb = [max(0, min(255, int(c))) for c in lrgb]
        raw_btns = data.get("button_actions")
        if isinstance(raw_btns, dict):
            for k, v in raw_btns.items():
                sk = int(k)
                if sk in INPHIC_SLOTS and str(v) in INPHIC_ACTION_CODE_BY_KEY:
                    st.button_actions[sk] = str(v)
        return st


def load_inphic_state(path: str = INPHIC_STATE_PATH) -> InphicW1State:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return InphicW1State.from_json_dict(json.load(fh))
        except Exception:
            pass
    return InphicW1State()


def save_inphic_state(state: InphicW1State, path: str = INPHIC_STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state.to_json_dict(), fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class InphicW1Session:
    """Context-managed session for writing Report 0x07 packets to Inphic W1."""

    def __init__(self, node: HidrawNode | None = None, settle: float = 0.018):
        self.node = node or find_inphic_w1_node()
        self.device = HidrawDevice(self.node.path)
        self.settle = settle

    def __enter__(self) -> "InphicW1Session":
        self.device.open()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.device.close()

    def _send_packet(self, pkt: bytes) -> None:
        transfer_len = self.node.transfer_len(RID_INPHIC_CFG) or 8
        buf = bytearray(pkt[:transfer_len])
        if len(buf) < transfer_len:
            buf.extend(b"\x00" * (transfer_len - len(buf)))
        if self.settle:
            time.sleep(self.settle)
        self.device.set_feature(buf)

    def write_dpi(self, state: InphicW1State) -> None:
        for pkt in build_inphic_dpi_packets(state.stages_cpi, state.stages_enabled, state.current_stage):
            self._send_packet(pkt)

    def write_lighting(self, state: InphicW1State) -> None:
        self._send_packet(build_inphic_lighting_packet(state.light_mode))

    def write_buttons(self, state: InphicW1State) -> None:
        for pkt in build_inphic_button_packets(state.button_actions):
            self._send_packet(pkt)

    def write_all(self, state: InphicW1State) -> None:
        self.write_dpi(state)
        self.write_lighting(state)
        self.write_buttons(state)
