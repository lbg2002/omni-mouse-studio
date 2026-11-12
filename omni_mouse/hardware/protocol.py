"""Hardware wire protocol specifically calibrated and verified against Delux M618XSD (1d57:fa60).

Key hardware differences verified directly against live M618XSD (v11.01) vs gaming mice:
1. Reply byte[1] equals ``declared_length`` (56, 15, 9, 59, 10, 8), whereas some v11.08
   gaming mice echo ``declared_length + 2``. Both are accepted.
2. DPI stages in Report 0x04 are stored directly as 16-bit little-endian DPI integers:
   ``X = dpi & 0xFF`` at byte[8+i], ``Y = (dpi >> 8) & 0xFF`` at byte[16+i]
   (factory: 800=0x0320, 1200=0x04B0, 1600=0x0640, 2400=0x0960, 4000=0x0FA0),
   with 2x interpolation bit ``(1 << i)`` set in byte[6] & byte[7] when ``dpi > 2400``.
3. Lighting mode in Report 0x05 byte[3] is stored in the low nibble ``0x00..0x06``
   (factory default: ``0x02``), not shifted left by 4 bits.
4. Button slots in Report 0x08 map M618XSD's physical controls including the Thumb Scroll Wheel:
   Slot 1=Left, 2=Right, 3=Forward, 4=Backward, 5=Middle, 6=DPI,
   15=Thumb Wheel Up/Left (0x0B), 16=Thumb Wheel Down/Right (0x0C),
   17=Scroll Up (0x09), 18=Scroll Down (0x0A).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .keymap import hid_key_name, hid_key_usage

VENDOR_ID = 0x1D57
PID_DONGLE = 0xFA60
PID_WIRED_ALT1 = 0xFA61
PID_WIRED_ALT2 = 0xFA55
SUPPORTED_PIDS = (PID_DONGLE, PID_WIRED_ALT1, PID_WIRED_ALT2)

RID_EVENT = 0x03
RID_DPI = 0x04
RID_LIGHT = 0x05
RID_POLL = 0x06
RID_WAKE = 0x07
RID_BUTTONS = 0x08
RID_MACRO = 0x09
RID_PROFILE = 0x0A
RID_VERSION = 0x0B
RID_PROFILE_SET = 0x0C
RID_READ = 0xA0

DPI_LENGTH = 0x38          # 56 bytes
LIGHT_LENGTH = 0x0F        # 15 bytes
POLL_LENGTH = 0x09         # 9 bytes
WAKE_LENGTH = 0x08         # 8 bytes
BUTTON_LENGTH = 0x3B       # 59 bytes
VERSION_LENGTH = 0x08      # 8 bytes
PROFILE_SET_LENGTH = 0x0A  # 10 bytes
GRANT_LENGTH = 0x08        # 8 bytes
EVENT_LENGTH = 0x05        # 5 bytes

READ_GRANT_LENGTH = {
    RID_DPI: DPI_LENGTH,
    RID_LIGHT: LIGHT_LENGTH,
    RID_POLL: POLL_LENGTH,
    RID_WAKE: WAKE_LENGTH,
    RID_BUTTONS: BUTTON_LENGTH,
    RID_VERSION: VERSION_LENGTH,
    RID_PROFILE_SET: PROFILE_SET_LENGTH,
}

# Polling Rate (Report 0x06)
POLL_BY_BYTE = {0x08: 125, 0x04: 250, 0x02: 500, 0x01: 1000}
BYTE_BY_POLL = {hz: b for b, hz in POLL_BY_BYTE.items()}
POLL_RATES = (125, 250, 500, 1000)

# M618XSD DPI Constants (600 - 4000 DPI official, 400 - 4000 supported)
M618_DPI_MIN = 400
M618_DPI_MAX = 4000
M618_DPI_STEP = 100
M618_NATIVE_CPI_MAX = 2400
MAX_DPI_STAGES = 8
DEFAULT_M618_DPI = [800, 1200, 1600, 2400, 4000, 0, 0, 0]
DEFAULT_M618_COLORS = [
    (255, 0, 0),      # Stage 1: 800  - Red
    (0, 255, 0),      # Stage 2: 1200 - Green
    (0, 0, 255),      # Stage 3: 1600 - Blue
    (255, 0, 255),    # Stage 4: 2400 - Purple
    (255, 255, 0),    # Stage 5: 4000 - Yellow
    (0, 255, 255),
    (255, 64, 0),
    (255, 255, 255),
]

# M618XSD Lighting Modes (Report 0x05 byte[3] high nibble: mode << 4)
LIGHT_MODES: dict[int, tuple[str, str]] = {
    0x00: ("off", "关闭灯光 (全灭省电)"),
    0x08: ("stream", "炫彩流光模式 (M618XSD 默认)"),
    0x03: ("neon", "霓虹渐变循环"),
    0x02: ("breathing", "单色呼吸 (自定义 RGB)"),
    0x01: ("steady", "单色常亮 (自定义 RGB)"),
    0x04: ("color_breathing", "七彩循环呼吸"),
    0x05: ("dpi_steady", "跟随当前 DPI 档位色常亮"),
    0x06: ("dpi_breathing", "跟随当前 DPI 档位色呼吸"),
}
LIGHT_CODE_BY_KEY = {k: code for code, (k, _) in LIGHT_MODES.items()}

# Firmware Button Actions (Report 0x08) — including M618XSD Thumb Wheel 0x0B / 0x0C!
FIRMWARE_ACTIONS: dict[int, tuple[str, str]] = {
    0x00: ("unused", "未分配"),
    0x01: ("disabled", "禁用按键"),
    0x02: ("left-click", "左键点击"),
    0x03: ("right-click", "右键点击"),
    0x04: ("middle-click", "滚轮中键"),
    0x05: ("backward", "侧键：后退 (Backward)"),
    0x06: ("forward", "侧键：前进 (Forward)"),
    0x07: ("double-click", "左键双击"),
    0x08: ("fire", "连发键 (Fire)"),
    0x09: ("scroll-up", "垂直向上滚动"),
    0x0A: ("scroll-down", "垂直向下滚动"),
    0x0B: ("scroll-left", "横向左滚 (拇指滚轮上拨)"),
    0x0C: ("scroll-right", "横向右滚 (拇指滚轮下拨)"),
    0x0D: ("dpi-cycle", "DPI 循环切换"),
    0x0E: ("dpi-plus", "DPI 档位 +"),
    0x0F: ("dpi-minus", "DPI 档位 -"),
    0x11: ("keyboard-key", "键盘快捷键组合"),
    0x15: ("media-player", "打开播放器"),
    0x16: ("previous-track", "上一曲"),
    0x17: ("next-track", "下一曲"),
    0x18: ("play-pause", "播放 / 暂停"),
    0x19: ("stop", "停止播放"),
    0x1A: ("mute", "静音"),
    0x1B: ("volume-up", "音量 +"),
    0x1C: ("volume-down", "音量 -"),
    0x1D: ("calculator", "打开计算器"),
    0x1E: ("email", "打开邮件"),
    0x20: ("browser-forward", "浏览器前进"),
    0x21: ("browser-backward", "浏览器后退"),
    0x23: ("my-computer", "打开文件管理器"),
    0x24: ("browser-refresh", "刷新页面"),
    0x25: ("browser-home", "浏览器主页"),
    0x26: ("browser-search", "搜索"),
    0x34: ("profile-cycle", "板载配置循环切换"),
    0x40: ("polling-rate-cycle", "回报率循环切换"),
}
ACTION_CODE_BY_KEY = {k: code for code, (k, _) in FIRMWARE_ACTIONS.items()}

HID_MODIFIERS = {
    "ctrl": 0x01,
    "shift": 0x02,
    "alt": 0x04,
    "super": 0x08,
}

# Verified M618XSD Physical Slot Mapping (from factory Report 0x08)
M618XSD_SLOTS: dict[int, str] = {
    1: "左键 (Left Click)",
    2: "右键 (Right Click)",
    3: "前进侧键 (Forward)",
    4: "后退侧键 (Backward)",
    5: "滚轮中键 (Middle Click)",
    6: "顶部 DPI 键 (DPI Cycle)",
    15: "拇指侧滚轮 · 上拨 (Thumb Up/Left)",
    16: "拇指侧滚轮 · 下拨 (Thumb Down/Right)",
    17: "主滚轮 · 上滚 (Scroll Up)",
    18: "主滚轮 · 下滚 (Scroll Down)",
}


class ProtocolError(ValueError):
    """Invalid or corrupted hardware report."""


def checksum16(buf: bytes | bytearray, start: int, end: int) -> int:
    return sum(buf[start:end]) & 0xFFFF


def _u16_be(buf: bytes | bytearray, offset: int) -> int:
    return (buf[offset] << 8) | buf[offset + 1]


def _put_u16_be(buf: bytearray, offset: int, value: int) -> None:
    value &= 0xFFFF
    buf[offset] = (value >> 8) & 0xFF
    buf[offset + 1] = value & 0xFF


def build_grant_request(rid: int, parameter: int = 0x01, declared_length: int | None = None) -> bytearray:
    if declared_length is None:
        declared_length = READ_GRANT_LENGTH[rid]
    buf = bytearray(GRANT_LENGTH)
    buf[0] = RID_READ
    buf[1] = rid & 0xFF
    buf[2] = declared_length & 0xFF
    buf[3] = 0x00
    buf[4] = parameter & 0xFF
    return buf


@dataclass
class DpiSettings:
    """Report 0x04 (56 bytes): M618XSD DPI stages, colors, and sensor flags."""

    profile: int = 1
    sensor_byte3: int = 0x08   # M618XSD factory sensor register byte 3
    sensor_byte4: int = 0x08   # M618XSD factory sensor register byte 4
    active_stages: int = 0x1F  # 5 stages active by default (bits 0..4)
    current_stage: int = 2     # Stage 2 = 1200 DPI default
    dpi: list[int] = field(default_factory=lambda: list(DEFAULT_M618_DPI))
    colors: list[tuple[int, int, int]] = field(default_factory=lambda: list(DEFAULT_M618_COLORS))
    indicator: int = 2

    def stage_enabled(self, stage: int) -> bool:
        return bool(self.active_stages & (1 << (stage - 1)))

    def set_stage_enabled(self, stage: int, enabled: bool) -> None:
        bit = 1 << (stage - 1)
        if enabled:
            self.active_stages |= bit
        else:
            if (self.active_stages & ~bit) != 0:  # Keep at least 1 stage enabled
                self.active_stages &= ~bit

    def set_stage_dpi(self, stage: int, value: int) -> None:
        idx = stage - 1
        if value <= 0:
            self.dpi[idx] = 0
        else:
            clamped = max(M618_DPI_MIN, min(M618_DPI_MAX, int(round(value / 50) * 50)))
            self.dpi[idx] = clamped

    def build(self) -> bytearray:
        buf = bytearray(DPI_LENGTH)
        buf[0] = RID_DPI
        buf[1] = DPI_LENGTH
        buf[2] = self.profile & 0xFF
        buf[3] = self.sensor_byte3 & 0xFF
        buf[4] = self.sensor_byte4 & 0xFF
        buf[5] = self.active_stages & 0xFF

        interp_mask = 0
        for idx in range(MAX_DPI_STAGES):
            val = max(0, int(self.dpi[idx]))
            buf[8 + idx] = val & 0xFF
            buf[16 + idx] = (val >> 8) & 0xFF
            if val > M618_NATIVE_CPI_MAX:
                interp_mask |= 1 << idx

        buf[6] = interp_mask
        buf[7] = interp_mask
        buf[24] = self.current_stage & 0xFF

        for idx in range(MAX_DPI_STAGES):
            r, g, b = self.colors[idx]
            base = 25 + 3 * idx
            buf[base] = r & 0xFF
            buf[base + 1] = g & 0xFF
            buf[base + 2] = b & 0xFF

        buf[49] = self.indicator & 0xFF
        _put_u16_be(buf, 50, checksum16(buf, 3, 50))
        return buf

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray, verify: bool = True) -> "DpiSettings":
        data = bytes(raw)
        if len(data) < 52:
            raise ProtocolError(f"DPI 报文长度不足: {len(data)}")
        if len(data) < DPI_LENGTH:
            data = data + b"\x00" * (DPI_LENGTH - len(data))
        if verify:
            expected = _u16_be(data, 50)
            actual = checksum16(data, 3, 50)
            if expected != actual:
                raise ProtocolError(f"DPI 校验和不匹配: {expected:#06x} != {actual:#06x}")

        dpis: list[int] = []
        colors: list[tuple[int, int, int]] = []
        for idx in range(MAX_DPI_STAGES):
            lo = data[8 + idx]
            hi = data[16 + idx]
            dpis.append((hi << 8) | lo)
            base = 25 + 3 * idx
            colors.append((data[base], data[base + 1], data[base + 2]))

        return cls(
            profile=data[2],
            sensor_byte3=data[3],
            sensor_byte4=data[4],
            active_stages=data[5],
            current_stage=data[24],
            dpi=dpis,
            colors=colors,
            indicator=data[49],
        )

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "active_stages_mask": self.active_stages,
            "current_stage": self.current_stage,
            "stages": [
                {
                    "stage": i + 1,
                    "enabled": self.stage_enabled(i + 1),
                    "dpi": self.dpi[i],
                    "rgb": list(self.colors[i]),
                }
                for i in range(5)
            ],
        }


@dataclass
class LightingSettings:
    """Report 0x05 (15 bytes): M618XSD RGB lighting, sleep timers & key debounce."""

    profile: int = 1
    mode: int = 0x08                        # High nibble of byte[3]: 0x08 (0x80) = 流光模式
    led_speed: int = 3                      # 1..5
    brightness: int = 8                     # 1..8
    deep_sleep_minutes: int = 10            # 1..60 min
    rgb: tuple[int, int, int] = (0, 255, 0)
    light_sleep_minutes: float = 0.5        # 0.5..30.0 min in 0.5 steps
    debounce_ms: int = 8                    # 4..50 ms in 2ms steps
    _low_nibble: int = 0x00                 # Preserves firmware status nibble in byte[3]

    @property
    def mode_key(self) -> str:
        return LIGHT_MODES.get(self.mode, ("unknown", "未知"))[0]

    @property
    def mode_label(self) -> str:
        return LIGHT_MODES.get(self.mode, ("unknown", f"模式 0x{self.mode:02x}"))[1]

    def build(self) -> bytearray:
        buf = bytearray(LIGHT_LENGTH)
        buf[0] = RID_LIGHT
        buf[1] = LIGHT_LENGTH
        buf[2] = self.profile & 0xFF
        buf[3] = ((self.mode & 0x0F) << 4) | (self._low_nibble & 0x0F)
        deep = max(1, min(60, int(self.deep_sleep_minutes)))
        speed = max(1, min(5, int(self.led_speed)))
        bright = max(1, min(8, int(self.brightness)))
        buf[4] = (deep & 0xF0) | (speed & 0x0F)
        buf[5] = ((deep & 0x0F) << 4) | (bright & 0x0F)
        r, g, b = self.rgb
        buf[6], buf[7], buf[8] = r & 0xFF, g & 0xFF, b & 0xFF
        sleep_half = max(1, min(60, int(round(self.light_sleep_minutes * 2))))
        buf[9] = sleep_half
        deb = max(4, min(50, int(round(self.debounce_ms / 2) * 2)))
        buf[10] = deb // 2
        _put_u16_be(buf, 11, checksum16(buf, 3, 11))
        return buf

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray, verify: bool = True) -> "LightingSettings":
        data = bytes(raw)
        if len(data) < 13:
            raise ProtocolError(f"灯光报文长度不足: {len(data)}")
        if len(data) < LIGHT_LENGTH:
            data = data + b"\x00" * (LIGHT_LENGTH - len(data))
        if verify:
            expected = _u16_be(data, 11)
            actual = checksum16(data, 3, 11)
            if expected != actual:
                raise ProtocolError(f"灯光校验和不匹配: {expected:#06x} != {actual:#06x}")

        b3 = data[3]
        mode = (b3 >> 4) & 0x0F
        low_nib = b3 & 0x0F
        deep = (data[4] & 0xF0) | (data[5] >> 4)
        speed = data[4] & 0x0F
        bright = data[5] & 0x0F
        sleep_min = max(0.5, min(30.0, (data[9] or 1) * 0.5))
        debounce = max(4, min(50, (data[10] or 4) * 2))

        return cls(
            profile=data[2],
            mode=mode,
            led_speed=speed or 3,
            brightness=bright or 8,
            deep_sleep_minutes=deep or 10,
            rgb=(data[6], data[7], data[8]),
            light_sleep_minutes=sleep_min,
            debounce_ms=debounce,
            _low_nibble=low_nib,
        )

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "mode": self.mode,
            "mode_key": self.mode_key,
            "mode_label": self.mode_label,
            "led_speed": self.led_speed,
            "brightness": self.brightness,
            "rgb": list(self.rgb),
            "light_sleep_minutes": self.light_sleep_minutes,
            "deep_sleep_minutes": self.deep_sleep_minutes,
            "debounce_ms": self.debounce_ms,
        }


@dataclass
class PollingRate:
    """Report 0x06 (9 bytes): USB/2.4G Polling Rate."""

    profile: int = 1
    hz: int = 250

    def build(self) -> bytearray:
        if self.hz not in BYTE_BY_POLL:
            raise ProtocolError(f"不支持的回报率: {self.hz} Hz (支持 125/250/500/1000)")
        code = BYTE_BY_POLL[self.hz]
        buf = bytearray(POLL_LENGTH)
        buf[0] = RID_POLL
        buf[1] = POLL_LENGTH
        buf[2] = self.profile & 0xFF
        buf[3] = code
        buf[4] = (0xFF - code) & 0xFF
        return buf

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray) -> "PollingRate":
        data = bytes(raw)
        if len(data) < 5:
            raise ProtocolError(f"回报率报文过短: {len(data)}")
        code = data[3]
        if code not in POLL_BY_BYTE:
            raise ProtocolError(f"未知回报率字节: {code:#04x}")
        return cls(profile=data[2], hz=POLL_BY_BYTE[code])

    def to_dict(self) -> dict:
        return {"profile": self.profile, "hz": self.hz}


@dataclass
class ButtonSlot:
    action: int = 0x00
    modifiers: int = 0x00
    usage: int = 0x00

    @property
    def action_key(self) -> str:
        return FIRMWARE_ACTIONS.get(self.action, (f"0x{self.action:02x}", "未知"))[0]

    def describe(self) -> str:
        if self.action == 0x11:  # keyboard-key
            mods = [name.capitalize() for name, bit in HID_MODIFIERS.items() if self.modifiers & bit]
            mods.append(hid_key_name(self.usage))
            return "快捷键: " + "+".join(mods)
        return FIRMWARE_ACTIONS.get(self.action, ("unknown", f"代码 0x{self.action:02x}"))[1]

    @classmethod
    def from_combo(cls, combo: str) -> "ButtonSlot":
        parts = [p.strip() for p in combo.split("+") if p.strip()]
        mods = 0
        key_part = None
        for p in parts:
            low = p.lower()
            if low in ("ctrl", "control"):
                mods |= HID_MODIFIERS["ctrl"]
            elif low == "shift":
                mods |= HID_MODIFIERS["shift"]
            elif low == "alt":
                mods |= HID_MODIFIERS["alt"]
            elif low in ("super", "win", "meta"):
                mods |= HID_MODIFIERS["super"]
            else:
                key_part = p
        if key_part is None:
            raise ProtocolError(f"组合键缺少主键: {combo!r}")
        return cls(action=0x11, modifiers=mods, usage=hid_key_usage(key_part))


@dataclass
class ButtonSettings:
    """Report 0x08 (59 bytes): 18 3-byte button slots + 2-byte big-endian checksum."""

    profile: int = 1
    slots: list[ButtonSlot] = field(default_factory=lambda: [ButtonSlot() for _ in range(18)])

    def slot(self, number: int) -> ButtonSlot:
        return self.slots[number - 1]

    def set_slot(self, number: int, slot: ButtonSlot) -> None:
        self.slots[number - 1] = slot

    def build(self) -> bytearray:
        buf = bytearray(BUTTON_LENGTH)
        buf[0] = RID_BUTTONS
        buf[1] = BUTTON_LENGTH
        buf[2] = self.profile & 0xFF
        for idx, sl in enumerate(self.slots[:18]):
            off = 3 + 3 * idx
            buf[off] = sl.action & 0xFF
            buf[off + 1] = sl.modifiers & 0xFF
            buf[off + 2] = sl.usage & 0xFF
        _put_u16_be(buf, 57, checksum16(buf, 3, 57))
        return buf

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray, verify: bool = True) -> "ButtonSettings":
        data = bytes(raw)
        if len(data) < BUTTON_LENGTH:
            raise ProtocolError(f"按键报文长度不足: {len(data)}")
        if verify:
            actual = checksum16(data, 3, 57)
            found = _u16_be(data, 57)
            if found not in (actual, actual & 0xFF):
                raise ProtocolError(f"按键校验和不匹配: {found:#06x} != {actual:#06x}")
        slots = [
            ButtonSlot(data[3 + 3 * i], data[4 + 3 * i], data[5 + 3 * i])
            for i in range(18)
        ]
        return cls(profile=data[2], slots=slots)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "m618xsd_slots": [
                {
                    "slot": num,
                    "label": label,
                    "action": self.slot(num).action_key,
                    "description": self.slot(num).describe(),
                }
                for num, label in M618XSD_SLOTS.items()
            ],
        }


@dataclass
class ProfileSettings:
    """Report 0x0C (10 bytes): Active onboard profile (1..2)."""

    current: int = 1
    maximum: int = 2

    def build(self) -> bytearray:
        buf = bytearray(PROFILE_SET_LENGTH)
        buf[0] = RID_PROFILE_SET
        buf[1] = PROFILE_SET_LENGTH
        buf[2] = self.current & 0xFF
        buf[3] = (~self.current) & 0xFF
        buf[4] = self.maximum & 0xFF
        buf[5] = (~self.maximum) & 0xFF
        return buf

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray) -> "ProfileSettings":
        data = bytes(raw)
        if len(data) < 6:
            raise ProtocolError("Profile 报文过短")
        return cls(current=max(1, data[2]), maximum=max(1, data[4]))


@dataclass(frozen=True)
class BatteryEvent:
    state: int = 1      # 1=放电中, 2=已充满, 3=充电中
    percent: int = 0

    @property
    def state_label(self) -> str:
        return {1: "电池供电中", 2: "已充满", 3: "正在充电"}.get(self.state, "在线")

    @property
    def charging(self) -> bool:
        return self.state in (2, 3)


@dataclass(frozen=True)
class DpiCycleEvent:
    stage: int = 1


@dataclass(frozen=True)
class ProfileChangedEvent:
    profile: int = 1


def decode_interrupt_event(raw: bytes) -> BatteryEvent | DpiCycleEvent | ProfileChangedEvent | None:
    if len(raw) != EVENT_LENGTH or raw[0] != RID_EVENT:
        return None
    _, code, p1, p2 = raw[1], raw[2], raw[3], raw[4]
    if code in (0x40, 0x41):
        return BatteryEvent(state=p1, percent=max(0, min(100, p2)))
    if code == 0x10:
        return DpiCycleEvent(stage=p1)
    if code == 0x80:
        return ProfileChangedEvent(profile=p1 + 1)
    return None
