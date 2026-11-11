"""Pure-stdlib Linux hidraw transport for Delux M618XSD."""

from __future__ import annotations

import array
import errno
import fcntl
import glob
import os
import select
from dataclasses import dataclass, field

_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, typ: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(typ) << 8) | nr


def HIDIOCSFEATURE(size: int) -> int:
    return _ioc(_IOC_READ | _IOC_WRITE, "H", 0x06, size)


def HIDIOCGFEATURE(size: int) -> int:
    return _ioc(_IOC_READ | _IOC_WRITE, "H", 0x07, size)


class HidrawError(OSError):
    """Error communicating with a /dev/hidraw node."""


def _describe_error(exc: OSError, path: str) -> str:
    if exc.errno in (errno.EACCES, errno.EPERM):
        return f"没有权限访问 {path}，请点击界面右上角「一键修复设备权限」或运行 udev/install-udev.sh"
    if exc.errno == errno.EPIPE:
        return f"{path} 通信超时/中断 (EPIPE)，请确认鼠标开关已打开且处于 2.4G 或有线连接状态"
    if exc.errno == errno.EINVAL:
        return f"{path} 内核拒绝了 HID 报文长度或 Report ID (EINVAL)"
    return f"{path}: {exc.strerror or exc}"


_TAG_REPORT_ID = 0x84
_TAG_REPORT_SIZE = 0x74
_TAG_REPORT_COUNT = 0x94
_MAIN_ITEMS = {0x80: "input", 0x90: "output", 0xB0: "feature"}


def parse_report_lengths(descriptor: bytes) -> dict[int, dict[str, int]]:
    """Parse HID report descriptor into {report_id: {'input': n, 'output': n, 'feature': n}}."""
    out: dict[int, dict[str, int]] = {}
    rid = 0
    size = 0
    count = 0
    i = 0
    end = len(descriptor)
    while i < end:
        b = descriptor[i]
        if b == 0xFE:
            i += 2 + descriptor[i + 1]
            continue
        tag = b & 0xFC
        blen = b & 0x03
        blen = 4 if blen == 3 else blen
        data = int.from_bytes(descriptor[i + 1 : i + 1 + blen], "little") if blen else 0
        if tag == _TAG_REPORT_ID:
            rid = data
        elif tag == _TAG_REPORT_SIZE:
            size = data
        elif tag == _TAG_REPORT_COUNT:
            count = data
        elif tag in _MAIN_ITEMS:
            kind = _MAIN_ITEMS[tag]
            slot = out.setdefault(rid, {})
            slot[kind] = slot.get(kind, 0) + (size * count + 7) // 8
        i += 1 + blen
    return out


def _sysfs_interface(path: str) -> int | None:
    probe = os.path.realpath(path)
    for _ in range(6):
        probe = os.path.dirname(probe)
        if probe in ("", "/", "/sys"):
            return None
        candidate = os.path.join(probe, "bInterfaceNumber")
        if os.path.exists(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    return int(fh.read().strip(), 16)
            except (OSError, ValueError):
                return None
    return None


@dataclass
class HidrawNode:
    path: str
    vid: int
    pid: int
    name: str = ""
    phys: str = ""
    uniq: str = ""
    interface: int | None = None
    descriptor: bytes = b""
    _lengths: dict[int, dict[str, int]] | None = field(default=None, repr=False)

    @property
    def report_lengths(self) -> dict[int, dict[str, int]]:
        if self._lengths is None:
            self._lengths = parse_report_lengths(self.descriptor)
        return self._lengths

    @property
    def features(self) -> dict[int, int]:
        return {
            rid: kinds["feature"]
            for rid, kinds in self.report_lengths.items()
            if kinds.get("feature")
        }

    def transfer_len(self, rid: int) -> int:
        feat = self.features
        if rid not in feat:
            raise HidrawError(f"{self.path} 不支持 Feature Report 0x{rid:02x}")
        return feat[rid] + 1

    @property
    def accessible(self) -> bool:
        return os.access(self.path, os.R_OK | os.W_OK)


def enumerate_hidraw() -> list[HidrawNode]:
    roots = sorted(
        glob.glob("/sys/class/hidraw/hidraw*"),
        key=lambda p: int(p.rsplit("hidraw", 1)[1]),
    )
    nodes: list[HidrawNode] = []
    for root in roots:
        try:
            with open(os.path.join(root, "device", "uevent"), encoding="utf-8") as fh:
                props = dict(
                    line.split("=", 1) for line in fh.read().splitlines() if "=" in line
                )
            with open(os.path.join(root, "device", "report_descriptor"), "rb") as fh:
                desc = fh.read()
        except OSError:
            continue
        parts = props.get("HID_ID", "").split(":")
        if len(parts) != 3:
            continue
        nodes.append(
            HidrawNode(
                path="/dev/" + os.path.basename(root),
                vid=int(parts[1], 16),
                pid=int(parts[2], 16),
                name=props.get("HID_NAME", ""),
                phys=props.get("HID_PHYS", ""),
                uniq=props.get("HID_UNIQ", ""),
                interface=_sysfs_interface(root),
                descriptor=desc,
            )
        )
    return nodes


class HidrawDevice:
    def __init__(self, path: str):
        self.path = path
        self.fd: int | None = None
        self.last_transfer: int | None = None

    def open(self) -> "HidrawDevice":
        if self.fd is not None:
            return self
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            raise HidrawError(_describe_error(exc, self.path)) from exc
        return self

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None

    def __enter__(self) -> "HidrawDevice":
        return self.open()

    def __exit__(self, *exc_info) -> None:
        self.close()

    def get_feature(self, rid: int, transfer_len: int) -> bytearray:
        if self.fd is None:
            raise HidrawError("设备尚未打开")
        buf = array.array("B", [0] * transfer_len)
        buf[0] = rid & 0xFF
        try:
            self.last_transfer = fcntl.ioctl(
                self.fd, HIDIOCGFEATURE(transfer_len), buf, True
            )
        except OSError as exc:
            self.last_transfer = None
            raise HidrawError(_describe_error(exc, self.path)) from exc
        return bytearray(buf)

    def set_feature(self, payload: bytes | bytearray) -> None:
        if self.fd is None:
            raise HidrawError("设备尚未打开")
        buf = array.array("B", bytes(payload))
        try:
            fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(buf)), buf, True)
        except OSError as exc:
            raise HidrawError(_describe_error(exc, self.path)) from exc

    def read(self, size: int = 64) -> bytes | None:
        if self.fd is None:
            raise HidrawError("设备尚未打开")
        try:
            return os.read(self.fd, size)
        except BlockingIOError:
            return None
        except OSError as exc:
            if exc.errno == errno.EAGAIN:
                return None
            raise HidrawError(_describe_error(exc, self.path)) from exc

    def wait_readable(self, timeout: float) -> bool:
        if self.fd is None:
            raise HidrawError("设备尚未打开")
        ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        return bool(ready)
