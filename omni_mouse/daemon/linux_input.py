"""Pure-stdlib Linux evdev reader & dual uinput virtual mouse/keyboard emitter."""

from __future__ import annotations

import fcntl
import glob
import os
import struct
import time
from dataclasses import dataclass

from ..hardware.keymap import EVDEV_KEYS

# Event types
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_MSC = 0x04

SYN_REPORT = 0x00

# Relative axes
REL_X = 0x00
REL_Y = 0x01
REL_HWHEEL = 0x06
REL_WHEEL = 0x08
REL_WHEEL_HI_RES = 0x0B
REL_HWHEEL_HI_RES = 0x0C

# Mouse button codes
BTN_LEFT = 0x110
BTN_RIGHT = 0x111
BTN_MIDDLE = 0x112
BTN_SIDE = 0x113    # M618XSD Backward
BTN_EXTRA = 0x114   # M618XSD Forward

KEY_MINUS = 12
KEY_EQUAL = 13
KEY_LEFTCTRL = 29

# struct input_event on 64-bit Linux: (tv_sec: q, tv_usec: q, type: H, code: H, value: i) = 24 bytes
EVENT_STRUCT = struct.Struct("llHHi")

# ioctl helpers
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, typ: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(typ) << 8) | nr


def EVIOCGID() -> int:
    return _ioc(_IOC_READ, "E", 0x02, 8)


def EVIOCGNAME(length: int) -> int:
    return _ioc(_IOC_READ, "E", 0x06, length)


def EVIOCGKEY(length: int) -> int:
    return _ioc(_IOC_READ, "E", 0x18, length)


def EVIOCGBIT(ev: int, length: int) -> int:
    return _ioc(_IOC_READ, "E", 0x20 + ev, length)


EVIOCGRAB = _ioc(_IOC_WRITE, "E", 0x90, 4)

# uinput ioctls (<linux/uinput.h>)
UI_DEV_CREATE = _ioc(0, "U", 1, 0)
UI_DEV_DESTROY = _ioc(0, "U", 2, 0)
UI_DEV_SETUP = _ioc(_IOC_WRITE, "U", 3, 92)
UI_SET_EVBIT = _ioc(_IOC_WRITE, "U", 100, 4)
UI_SET_KEYBIT = _ioc(_IOC_WRITE, "U", 101, 4)
UI_SET_RELBIT = _ioc(_IOC_WRITE, "U", 102, 4)

BUS_VIRTUAL = 0x06
VIRTUAL_VENDOR = 0x1D58   # Distinct from physical 0x1D57 so we never grab our own virtual device


def _bits_set(buf: bytes | bytearray) -> set[int]:
    out: set[int] = set()
    for byte_idx, b in enumerate(buf):
        if not b:
            continue
        for bit in range(8):
            if b & (1 << bit):
                out.add(byte_idx * 8 + bit)
    return out


SUPPORTED_MOUSE_VIDS: dict[int, str] = {
    0x1D57: "delux_m618xsd",  # Delux M618XSD (2.4G / Wired)
    0x30FA: "inphic_w1",      # Inphic W1 (Instant A704 / A725 USB Gaming Mouse)
    0x18F8: "inphic_w1",      # Instant A704F variant
}


@dataclass
class EvdevMouseNode:
    path: str
    name: str
    vid: int
    pid: int
    model_key: str = "delux_m618xsd"


def list_supported_mouse_evdev() -> list[EvdevMouseNode]:
    """Locate all connected physical mouse /dev/input/eventN nodes (Delux M618XSD & Inphic W1)."""
    found: list[EvdevMouseNode] = []
    for path in sorted(glob.glob("/dev/input/event*"), key=lambda p: int(p.rsplit("event", 1)[1])):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            id_buf = bytearray(8)
            fcntl.ioctl(fd, EVIOCGID(), id_buf, True)
            bustype, vendor, product, _ = struct.unpack("HHHH", id_buf)
            model_key = SUPPORTED_MOUSE_VIDS.get(vendor)
            if model_key is None or bustype == BUS_VIRTUAL:
                continue
            ev_buf = bytearray(4)
            fcntl.ioctl(fd, EVIOCGBIT(0, 4), ev_buf, True)
            evs = _bits_set(ev_buf)
            if EV_KEY not in evs or EV_REL not in evs:
                continue
            key_buf = bytearray(96)
            fcntl.ioctl(fd, EVIOCGBIT(EV_KEY, 96), key_buf, True)
            keys = _bits_set(key_buf)
            rel_buf = bytearray(8)
            fcntl.ioctl(fd, EVIOCGBIT(EV_REL, 8), rel_buf, True)
            rels = _bits_set(rel_buf)
            if BTN_LEFT in keys and REL_X in rels:
                name_buf = bytearray(256)
                fcntl.ioctl(fd, EVIOCGNAME(256), name_buf, True)
                name = bytes(name_buf).split(b"\x00", 1)[0].decode("utf-8", errors="replace")
                found.append(EvdevMouseNode(path=path, name=name, vid=vendor, pid=product, model_key=model_key))
        except OSError:
            continue
        finally:
            os.close(fd)
    return found


def find_inaccessible_mouse_evdev() -> list[str]:
    """Detect supported mouse /dev/input/eventN nodes that exist in sysfs but lack read access."""
    blocked: list[str] = []
    for sys_ev in sorted(glob.glob("/sys/class/input/event*")):
        uevent = os.path.join(sys_ev, "device", "uevent")
        if not os.path.exists(uevent):
            continue
        try:
            with open(uevent, encoding="utf-8", errors="ignore") as fh:
                txt = fh.read().upper()
        except OSError:
            continue
        if not any(tag in txt for tag in ("/1D57/", "/30FA/", "/18F8/")):
            continue
        if "EV=17" not in txt and "EV=1F" not in txt:
            continue
        devnode = f"/dev/input/{os.path.basename(sys_ev)}"
        if os.path.exists(devnode) and not os.access(devnode, os.R_OK):
            blocked.append(devnode)
    return blocked


def find_supported_mouse_evdev(preferred_model: str | None = None) -> EvdevMouseNode | None:
    """Return the preferred or first available supported physical mouse node."""
    nodes = list_supported_mouse_evdev()
    if not nodes:
        return None
    if preferred_model:
        for n in nodes:
            if n.model_key == preferred_model:
                return n
    return nodes[0]


def find_m618xsd_mouse_evdev() -> EvdevMouseNode | None:
    """Backward-compatible helper returning any supported mouse node."""
    return find_supported_mouse_evdev()


class PhysicalMouseReader:
    """Opens and exclusively grabs the physical M618XSD mouse event node."""

    def __init__(self, path: str):
        self.path = path
        self.fd: int | None = None
        self.grabbed = False

    def open_and_grab(self) -> None:
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        # Wait up to 400ms for any physically held mouse button to release before grabbing
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            key_state = bytearray(96)
            try:
                fcntl.ioctl(self.fd, EVIOCGKEY(96), key_state, True)
                held = _bits_set(key_state) & {BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA}
                if not held:
                    break
            except OSError:
                break
            time.sleep(0.02)
        fcntl.ioctl(self.fd, EVIOCGRAB, 1)
        self.grabbed = True

    def is_button_physically_held(self, btn_code: int) -> bool:
        """Query kernel evdev key bitmap directly so a dropped 2.4G release packet can never stick."""
        if self.fd is None:
            return False
        key_state = bytearray(96)
        try:
            fcntl.ioctl(self.fd, EVIOCGKEY(96), key_state, True)
            return btn_code in _bits_set(key_state)
        except OSError:
            return False

    def read_events(self) -> list[tuple[int, int, int]]:
        if self.fd is None:
            return []
        try:
            raw = os.read(self.fd, EVENT_STRUCT.size * 32)
        except BlockingIOError:
            return []
        except OSError as exc:
            if exc.errno == 11:  # EAGAIN
                return []
            raise
        out: list[tuple[int, int, int]] = []
        for offset in range(0, len(raw) - (len(raw) % EVENT_STRUCT.size), EVENT_STRUCT.size):
            _, _, ev_type, code, value = EVENT_STRUCT.unpack_from(raw, offset)
            out.append((ev_type, code, value))
        return out

    def close(self) -> None:
        if self.fd is not None:
            if self.grabbed:
                try:
                    fcntl.ioctl(self.fd, EVIOCGRAB, 0)
                except OSError:
                    pass
                self.grabbed = False
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


def _setup_uinput_device(name: str, product_id: int, rel_bits: list[int], key_bits: list[int]) -> int:
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
        if key_bits:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            for k in key_bits:
                fcntl.ioctl(fd, UI_SET_KEYBIT, k)
        if rel_bits:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
            for r in rel_bits:
                fcntl.ioctl(fd, UI_SET_RELBIT, r)
        # struct uinput_setup: input_id (HHHH = 8B) + name (80B) + ff_effects_max (I = 4B) = 92 bytes
        encoded_name = name.encode("utf-8")[:79]
        setup_buf = struct.pack("HHHH80sI", BUS_VIRTUAL, VIRTUAL_VENDOR, product_id, 1, encoded_name, 0)
        fcntl.ioctl(fd, UI_DEV_SETUP, setup_buf)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        return fd
    except Exception:
        os.close(fd)
        raise


class VirtualInputPair:
    """Dedicated virtual pointer + virtual keyboard for clean libinput/Wayland classification."""

    def __init__(self) -> None:
        self.mouse_fd: int | None = None
        self.kbd_fd: int | None = None

    def open(self) -> None:
        mouse_btns = [BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA]
        mouse_rels = [REL_X, REL_Y, REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES]
        self.mouse_fd = _setup_uinput_device("Delux M618XSD Smart Pointer", 0x0001, mouse_rels, mouse_btns)

        kbd_keys = sorted({code for code in EVDEV_KEYS.values() if code < 0x110})
        self.kbd_fd = _setup_uinput_device("Delux M618XSD Smart Keyboard", 0x0002, [], kbd_keys)

    def _write(self, fd: int | None, events: list[tuple[int, int, int]]) -> None:
        if fd is None or not events:
            return
        payload = b"".join(EVENT_STRUCT.pack(0, 0, t, c, int(v)) for t, c, v in events)
        os.write(fd, payload)

    def emit_mouse(self, events: list[tuple[int, int, int]], sync: bool = True) -> None:
        seq = list(events)
        if sync:
            seq.append((EV_SYN, SYN_REPORT, 0))
        self._write(self.mouse_fd, seq)

    def emit_key_combo(self, key_codes: list[int]) -> None:
        if not key_codes:
            return
        down = [(EV_KEY, k, 1) for k in key_codes] + [(EV_SYN, SYN_REPORT, 0)]
        self._write(self.kbd_fd, down)
        time.sleep(0.012)
        up = [(EV_KEY, k, 0) for k in reversed(key_codes)] + [(EV_SYN, SYN_REPORT, 0)]
        self._write(self.kbd_fd, up)

    def emit_zoom(self, direction: int, mode: str = "wheel") -> None:
        """Zoom via Ctrl+Equal/Minus (universal GTK4/Loupe/Papers) or Ctrl+Wheel (WPS/Canvas)."""
        if mode == "keys":
            key = KEY_EQUAL if direction > 0 else KEY_MINUS
            self.emit_key_combo([KEY_LEFTCTRL, key])
            return
        step = 1 if direction > 0 else -1
        self._write(self.kbd_fd, [(EV_KEY, KEY_LEFTCTRL, 1), (EV_SYN, SYN_REPORT, 0)])
        time.sleep(0.018)
        self.emit_mouse([(EV_REL, REL_WHEEL, step), (EV_REL, REL_WHEEL_HI_RES, step * 120)], sync=True)
        time.sleep(0.018)
        self._write(self.kbd_fd, [(EV_KEY, KEY_LEFTCTRL, 0), (EV_SYN, SYN_REPORT, 0)])

    def emit_scroll(self, axis: str, step: int) -> None:
        if axis == "h":
            self.emit_mouse([(EV_REL, REL_HWHEEL, step), (EV_REL, REL_HWHEEL_HI_RES, step * 120)], sync=True)
        else:
            self.emit_mouse([(EV_REL, REL_WHEEL, step), (EV_REL, REL_WHEEL_HI_RES, step * 120)], sync=True)

    def close(self) -> None:
        for attr in ("mouse_fd", "kbd_fd"):
            fd = getattr(self, attr)
            if fd is not None:
                try:
                    fcntl.ioctl(fd, UI_DEV_DESTROY)
                except OSError:
                    pass
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, attr, None)
