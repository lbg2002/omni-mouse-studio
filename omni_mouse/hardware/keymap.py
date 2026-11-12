"""Unified key mapping between USB HID Usage IDs, Linux evdev KEY_* codes, and human names."""

from __future__ import annotations

# USB HID Usage Page 0x07 (Keyboard/Keypad) -> Display Name
HID_KEY_NAMES: dict[int, str] = {0x00: "None"}
HID_KEY_NAMES.update({0x04 + i: chr(ord("A") + i) for i in range(26)})
HID_KEY_NAMES.update({0x1E + i: str((i + 1) % 10) for i in range(10)})
HID_KEY_NAMES.update(
    {
        0x28: "Enter",
        0x29: "Esc",
        0x2A: "Backspace",
        0x2B: "Tab",
        0x2C: "Space",
        0x2D: "-",
        0x2E: "=",
        0x2F: "[",
        0x30: "]",
        0x31: "\\",
        0x33: ";",
        0x34: "'",
        0x35: "`",
        0x36: ",",
        0x37: ".",
        0x38: "/",
        0x39: "CapsLock",
        0x46: "PrintScreen",
        0x49: "Insert",
        0x4A: "Home",
        0x4B: "PageUp",
        0x4C: "Delete",
        0x4D: "End",
        0x4E: "PageDown",
        0x4F: "Right",
        0x50: "Left",
        0x51: "Down",
        0x52: "Up",
        0xE0: "Ctrl",
        0xE1: "Shift",
        0xE2: "Alt",
        0xE3: "Super",
    }
)
HID_KEY_NAMES.update({0x3A + i: f"F{i + 1}" for i in range(12)})

HID_USAGE_BY_NAME: dict[str, int] = {
    name.lower(): code for code, name in HID_KEY_NAMES.items()
}
HID_USAGE_BY_NAME.update(
    {
        "escape": 0x29,
        "return": 0x28,
        "pgup": 0x4B,
        "page_up": 0x4B,
        "prior": 0x4B,
        "pgdn": 0x4E,
        "page_down": 0x4E,
        "next": 0x4E,
        "minus": 0x2D,
        "equal": 0x2E,
        "plus": 0x2E,
        "bracketleft": 0x2F,
        "bracketright": 0x30,
        "backslash": 0x31,
        "semicolon": 0x33,
        "apostrophe": 0x34,
        "grave": 0x35,
        "comma": 0x36,
        "period": 0x37,
        "slash": 0x38,
        "win": 0xE3,
        "meta": 0xE3,
    }
)

# Linux <linux/input-event-codes.h> EV_KEY constants
EVDEV_KEYS: dict[str, int] = {
    "ESC": 1,
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "0": 11,
    "MINUS": 12,
    "EQUAL": 13,
    "BACKSPACE": 14,
    "TAB": 15,
    "Q": 16,
    "W": 17,
    "E": 18,
    "R": 19,
    "T": 20,
    "Y": 21,
    "U": 22,
    "I": 23,
    "O": 24,
    "P": 25,
    "LEFTBRACE": 26,
    "RIGHTBRACE": 27,
    "ENTER": 28,
    "CTRL": 29,
    "LEFTCTRL": 29,
    "A": 30,
    "S": 31,
    "D": 32,
    "F": 33,
    "G": 34,
    "H": 35,
    "J": 36,
    "K": 37,
    "L": 38,
    "SEMICOLON": 39,
    "APOSTROPHE": 40,
    "GRAVE": 41,
    "SHIFT": 42,
    "LEFTSHIFT": 42,
    "BACKSLASH": 43,
    "Z": 44,
    "X": 45,
    "C": 46,
    "V": 47,
    "B": 48,
    "N": 49,
    "M": 50,
    "COMMA": 51,
    "DOT": 52,
    "SLASH": 53,
    "RIGHTSHIFT": 54,
    "KPASTERISK": 55,
    "ALT": 56,
    "LEFTALT": 56,
    "SPACE": 57,
    "CAPSLOCK": 58,
    "F1": 59,
    "F2": 60,
    "F3": 61,
    "F4": 62,
    "F5": 63,
    "F6": 64,
    "F7": 65,
    "F8": 66,
    "F9": 67,
    "F10": 68,
    "F11": 87,
    "F12": 88,
    "RIGHTCTRL": 97,
    "SYSRQ": 99,
    "PRINTSCREEN": 99,
    "RIGHTALT": 100,
    "HOME": 102,
    "UP": 103,
    "PAGEUP": 104,
    "LEFT": 105,
    "RIGHT": 106,
    "END": 107,
    "DOWN": 108,
    "PAGEDOWN": 109,
    "INSERT": 110,
    "DELETE": 111,
    "MUTE": 113,
    "VOLUMEDOWN": 114,
    "VOLUMEUP": 115,
    "SUPER": 125,
    "LEFTMETA": 125,
    "WIN": 125,
    "RIGHTMETA": 126,
    "STOPCD": 166,
    "NEXTSONG": 163,
    "PLAYPAUSE": 164,
    "PREVIOUSSONG": 165,
    "BACK": 158,
    "FORWARD": 159,
    "REFRESH": 173,
    "CALC": 140,
    "FILE": 144,
    # Mouse buttons
    "BTN_LEFT": 0x110,
    "BTN_RIGHT": 0x111,
    "BTN_MIDDLE": 0x112,
    "BTN_SIDE": 0x113,   # Backward button on M618XSD
    "BTN_EXTRA": 0x114,  # Forward button on M618XSD
}

EVDEV_ALIASES: dict[str, str] = {
    "-": "MINUS",
    "=": "EQUAL",
    "+": "EQUAL",
    "[": "LEFTBRACE",
    "]": "RIGHTBRACE",
    "\\": "BACKSLASH",
    ";": "SEMICOLON",
    "'": "APOSTROPHE",
    "`": "GRAVE",
    ",": "COMMA",
    ".": "DOT",
    "/": "SLASH",
    "ESCAPE": "ESC",
    "RETURN": "ENTER",
    "PGUP": "PAGEUP",
    "PRIOR": "PAGEUP",
    "PGDN": "PAGEDOWN",
    "NEXT": "PAGEDOWN",
    "CONTROL": "CTRL",
    "CONTROL_L": "CTRL",
    "CONTROL_R": "RIGHTCTRL",
    "SHIFT_L": "SHIFT",
    "SHIFT_R": "RIGHTSHIFT",
    "ALT_L": "ALT",
    "ALT_R": "RIGHTALT",
    "SUPER_L": "SUPER",
    "SUPER_R": "RIGHTMETA",
    "META_L": "SUPER",
    "VOLUP": "VOLUMEUP",
    "VOLDOWN": "VOLUMEDOWN",
    "PLAY": "PLAYPAUSE",
}


def resolve_evdev_key(token: str) -> int:
    """Resolve a human/GTK key token (e.g. 'Ctrl', 'Tab', 'VolumeUp') to Linux EV_KEY code."""
    up = token.strip().upper()
    if up in EVDEV_ALIASES:
        up = EVDEV_ALIASES[up]
    if up in EVDEV_KEYS:
        return EVDEV_KEYS[up]
    raise ValueError(f"无法识别按键名称: {token!r}")


def parse_combo_to_evdev(combo: str) -> list[int]:
    """Parse 'Ctrl+Shift+Tab' into ordered list of EV_KEY codes [29, 42, 15]."""
    parts = [p.strip() for p in combo.split("+") if p.strip()]
    return [resolve_evdev_key(p) for p in parts]


def hid_key_name(usage: int) -> str:
    return HID_KEY_NAMES.get(usage, f"0x{usage:02X}")


def hid_key_usage(name: str | int) -> int:
    if isinstance(name, int):
        return name & 0xFF
    t = name.strip().lower()
    if t in HID_USAGE_BY_NAME:
        return HID_USAGE_BY_NAME[t]
    return int(t, 0) & 0xFF
