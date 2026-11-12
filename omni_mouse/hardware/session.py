"""Hardware session manager for Delux M618XSD."""

from __future__ import annotations

import json
import os
import time

from . import protocol as p
from .hidraw import HidrawDevice, HidrawError, HidrawNode, enumerate_hidraw

CONFIG_MARKERS = (p.RID_DPI, p.RID_READ)


class SessionError(RuntimeError):
    """Mouse hardware communication or discovery error."""


def is_config_node(node: HidrawNode) -> bool:
    return all(rid in node.features for rid in CONFIG_MARKERS)


def list_m618xsd_nodes() -> list[HidrawNode]:
    nodes = [
        node
        for node in enumerate_hidraw()
        if node.vid == p.VENDOR_ID and (node.pid in p.SUPPORTED_PIDS or is_config_node(node))
    ]
    return sorted(nodes, key=lambda n: (not is_config_node(n), n.path))


def find_m618xsd_node(node_path: str | None = None) -> HidrawNode:
    nodes = list_m618xsd_nodes()
    if node_path:
        matched = [n for n in nodes if n.path == node_path]
        if not matched:
            raise SessionError(f"找不到指定的设备节点: {node_path}")
        nodes = matched
    for candidate in nodes:
        if is_config_node(candidate):
            return candidate
    if not nodes:
        raise SessionError(
            "未检测到多彩 M618XSD 接收器或有线连接 (1d57:fa60)。请确认已插入 2.4G 接收器或连接数据线。"
        )
    raise SessionError("已检测到接收器，但未找到配置通道节点。")


class M618XSDSession:
    """Thread-safe / context-managed hardware session for reading & writing onboard settings."""

    def __init__(self, node: HidrawNode | None = None, grant_delay: float = 0.20, settle: float = 0.06):
        self.node = node or find_m618xsd_node()
        self.device = HidrawDevice(self.node.path)
        self.grant_delay = grant_delay
        self.settle = settle

    def __enter__(self) -> "M618XSDSession":
        self.device.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.device.close()

    def read_raw_report(self, rid: int, parameter: int = 0x01, retries: int = 1) -> bytes:
        if rid not in self.node.features:
            raise SessionError(f"{self.node.path} 不支持报告 0x{rid:02x}")
        transfer_len = self.node.transfer_len(rid)
        declared_len = p.READ_GRANT_LENGTH.get(rid, transfer_len)
        if rid == p.RID_PROFILE_SET:
            parameter = 0x00
        grant = p.build_grant_request(rid, parameter, declared_len)
        last_err = "无响应"
        for attempt in range(max(0, retries) + 1):
            try:
                if self.settle:
                    time.sleep(self.settle)
                self.device.set_feature(grant)
                time.sleep(self.grant_delay)
                status = self.device.get_feature(p.RID_READ, self.node.transfer_len(p.RID_READ))
                if status[1] != 0x01:
                    last_err = f"固件拒绝读取请求 (status={status[1]:#04x})"
                else:
                    frame = bytes(self.device.get_feature(rid, transfer_len))
                    # M618XSD v11.01 echoes declared_len; newer firmwares echo declared_len + 2
                    if frame[0] == rid and frame[1] in (declared_len, declared_len + 2, transfer_len):
                        return frame
                    last_err = f"返回报文头不匹配 ({frame[:4].hex(' ')})"
            except (HidrawError, OSError) as exc:
                last_err = str(exc)
            if attempt < retries:
                time.sleep(0.12 * (attempt + 1))
        raise SessionError(
            f"读取硬件配置 0x{rid:02x} 失败 ({last_err}) — 请确保鼠标底部电源已开启且未处于无线休眠（移动或点击一下鼠标后再点「同步硬件参数」）。"
        )

    def write_raw_report(self, payload: bytes | bytearray) -> bytes:
        raw = bytes(payload)
        rid = raw[0]
        transfer_len = self.node.transfer_len(rid)
        fitted = bytearray(raw[:transfer_len])
        if len(fitted) < transfer_len:
            fitted.extend(b"\x00" * (transfer_len - len(fitted)))
        if self.settle:
            time.sleep(self.settle)
        self.device.set_feature(fitted)
        return bytes(fitted)

    def read_dpi(self, profile: int = 1, retries: int = 1) -> p.DpiSettings:
        return p.DpiSettings.from_bytes(self.read_raw_report(p.RID_DPI, parameter=profile, retries=retries))

    def write_dpi(self, settings: p.DpiSettings, refresh_lighting: p.LightingSettings | None = None) -> None:
        if refresh_lighting is None:
            try:
                refresh_lighting = self.read_lighting()
            except Exception:
                refresh_lighting = None
        self.write_raw_report(settings.build())
        if refresh_lighting is not None:
            time.sleep(0.08)
            self.write_raw_report(refresh_lighting.build())

    def read_lighting(self, retries: int = 1) -> p.LightingSettings:
        return p.LightingSettings.from_bytes(self.read_raw_report(p.RID_LIGHT, retries=retries))

    def write_lighting(self, settings: p.LightingSettings) -> None:
        self.write_raw_report(settings.build())

    def read_polling(self, retries: int = 1) -> p.PollingRate:
        return p.PollingRate.from_bytes(self.read_raw_report(p.RID_POLL, retries=retries))

    def write_polling(self, settings: p.PollingRate) -> None:
        self.write_raw_report(settings.build())

    def read_buttons(self, profile: int = 1, retries: int = 1) -> p.ButtonSettings:
        return p.ButtonSettings.from_bytes(self.read_raw_report(p.RID_BUTTONS, parameter=profile, retries=retries))

    def write_buttons(self, settings: p.ButtonSettings) -> None:
        self.write_raw_report(settings.build())

    def read_profile_settings(self, retries: int = 1) -> p.ProfileSettings:
        return p.ProfileSettings.from_bytes(self.read_raw_report(p.RID_PROFILE_SET, retries=retries))

    def write_profile_settings(self, settings: p.ProfileSettings) -> None:
        self.write_raw_report(settings.build())

    def read_firmware_version(self, retries: int = 1) -> str:
        raw = self.read_raw_report(p.RID_VERSION, retries=retries)
        return f"v{raw[3]:X}.{raw[4]:02X} (ID 0x{raw[5]:02X})"

    def read_battery(self, timeout: float = 0.25) -> p.BatteryEvent | None:
        """Passively read any pending interrupt Report 0x03 without issuing invalid Feature 0xA0 grants."""
        end = time.monotonic() + max(0.05, timeout)
        latest: p.BatteryEvent | None = None
        while time.monotonic() < end:
            rem = end - time.monotonic()
            if rem <= 0 or not self.device.wait_readable(min(0.10, rem)):
                break
            pkt = self.device.read(64)
            if not pkt:
                break
            ev = p.decode_interrupt_event(pkt)
            if isinstance(ev, p.BatteryEvent):
                latest = ev
        return latest

    def read_all(self, profile: int = 1) -> dict:
        dpi = self.read_dpi(profile=profile)
        lighting = self.read_lighting()
        polling = self.read_polling()
        buttons = self.read_buttons(profile=profile)
        prof = self.read_profile_settings()
        fw = self.read_firmware_version()
        bat = self.read_battery(timeout=0.8)
        return {
            "node": self.node.path,
            "firmware": fw,
            "profile_settings": prof,
            "dpi": dpi,
            "lighting": lighting,
            "polling": polling,
            "buttons": buttons,
            "battery": bat,
        }

    def restore_backup_file(self, backup_path: str) -> list[str]:
        with open(backup_path, encoding="utf-8") as fh:
            data = json.load(fh)
        restored = []
        for hex_rid in ("0x04", "0x05", "0x06", "0x08"):
            if hex_rid in data:
                raw = bytes.fromhex(data[hex_rid])
                self.write_raw_report(raw)
                time.sleep(0.10)
                restored.append(hex_rid)
        return restored
