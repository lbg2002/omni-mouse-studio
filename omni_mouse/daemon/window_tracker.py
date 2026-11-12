"""Active window / application focus detection across GNOME Wayland (AT-SPI2 + Shell Extension), XWayland/X11 & Hyprland."""

from __future__ import annotations

import glob
import json
import os
import subprocess
import time
from dataclasses import dataclass

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib  # type: ignore

    HAS_GIO = True
except Exception:
    HAS_GIO = False


@dataclass(frozen=True)
class WindowInfo:
    app_id: str = ""
    wm_class: str = ""
    title: str = ""
    backend: str = "none"

    def display_label(self) -> str:
        primary = self.wm_class or self.app_id.replace(".desktop", "") or "桌面"
        if self.title:
            short_title = self.title if len(self.title) <= 36 else self.title[:35] + "…"
            return f"{primary} — {short_title}"
        return primary


class ActiveWindowTracker:
    """Fast multi-backend active-window resolver with 100ms caching & <1ms AT-SPI2 hot-path."""

    def __init__(self, cache_ttl: float = 0.10):
        self.cache_ttl = cache_ttl
        self._last_check = 0.0
        self._cached = WindowInfo()
        self._bus: Gio.DBusConnection | None = None
        self._a11y_conn: Gio.DBusConnection | None = None
        self._a11y_last_init_try = 0.0
        # Fast-path cache for currently active AT-SPI2 window: (win_sender, win_path, app_id, wm_class)
        self._active_atspi_win: tuple[str, str, str, str] | None = None
        self._sender_proc_cache: dict[str, tuple[str, str]] = {}

        if HAS_GIO:
            self._ensure_session_bus()

    def _ensure_session_bus(self) -> Gio.DBusConnection | None:
        if self._bus is not None and not self._bus.is_closed():
            return self._bus
        if not HAS_GIO:
            return None
        # Ensure DBUS_SESSION_BUS_ADDRESS is set even if started cleanly by systemd
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            candidate = f"/run/user/{os.getuid()}/bus"
            if os.path.exists(candidate):
                os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={candidate}"
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            self._bus = None
        return self._bus

    def _ensure_a11y_bus(self) -> Gio.DBusConnection | None:
        if self._a11y_conn is not None and not self._a11y_conn.is_closed():
            return self._a11y_conn
        now = time.monotonic()
        if now - self._a11y_last_init_try < 2.0:
            return None
        self._a11y_last_init_try = now

        bus = self._ensure_session_bus()
        if bus is None:
            return None
        try:
            # Ensure AT-SPI2 status is enabled so GTK4 / Chromium / Qt windows expose STATE_ACTIVE immediately
            try:
                bus.call_sync(
                    "org.a11y.Bus",
                    "/org/a11y/bus",
                    "org.freedesktop.DBus.Properties",
                    "Set",
                    GLib.Variant("(ssv)", ("org.a11y.Status", "IsEnabled", GLib.Variant("b", True))),
                    None,
                    Gio.DBusCallFlags.NONE,
                    250,
                    None,
                )
            except Exception:
                pass

            addr = bus.call_sync(
                "org.a11y.Bus",
                "/org/a11y/bus",
                "org.a11y.Bus",
                "GetAddress",
                None,
                GLib.VariantType("(s)"),
                Gio.DBusCallFlags.NONE,
                300,
                None,
            ).unpack()[0]
            if not addr:
                return None
            self._a11y_conn = Gio.DBusConnection.new_for_address_sync(
                addr,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None,
                None,
            )
            return self._a11y_conn
        except Exception:
            self._a11y_conn = None
            return None

    def current_window(self, force: bool = False) -> WindowInfo:
        now = time.monotonic()
        if not force and (now - self._last_check) < self.cache_ttl:
            return self._cached
        self._last_check = now
        info = (
            self._via_delux_gnome_extension()
            or self._via_atspi_bus()
            or self._via_xprop()
            or self._via_gnome_introspect_windows()
            or self._via_hyprland()
            or WindowInfo()
        )
        self._cached = info
        return info

    def _via_delux_gnome_extension(self) -> WindowInfo | None:
        bus = self._ensure_session_bus()
        if bus is None:
            return None
        for svc, obj_path, iface in (
            ("org.omnimouse.Studio.Focus", "/org/omnimouse/Studio/Focus", "org.omnimouse.Studio.Focus"),
            ("org.delux.M618XSD.Focus", "/org/delux/M618XSD/Focus", "org.delux.M618XSD.Focus"),
        ):
            try:
                res = bus.call_sync(
                    svc,
                    obj_path,
                    iface,
                    "GetFocusedWindow",
                    None,
                    GLib.VariantType("(sss)"),
                    Gio.DBusCallFlags.NO_AUTO_START,
                    60,
                    None,
                )
                app_id, wm_class, title = res.unpack()
                if app_id or wm_class or title:
                    return WindowInfo(app_id=app_id, wm_class=wm_class, title=title, backend="gnome-extension")
            except Exception:
                continue
        return None

    def _resolve_a11y_sender_proc(self, conn: Gio.DBusConnection, sender: str, fallback_name: str) -> tuple[str, str]:
        cached = self._sender_proc_cache.get(sender)
        if cached is not None:
            return cached
        exe_tag = ""
        comm_tag = ""
        try:
            pid = conn.call_sync(
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus",
                "GetConnectionUnixProcessID",
                GLib.Variant("(s)", (sender,)),
                GLib.VariantType("(u)"),
                Gio.DBusCallFlags.NONE,
                120,
                None,
            ).unpack()[0]
            if pid:
                try:
                    with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as fh:
                        comm_tag = fh.read().strip()
                except OSError:
                    pass
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as fh:
                        raw = fh.read(512).split(b"\x00")
                        if raw and raw[0]:
                            exe_tag = os.path.basename(raw[0].decode("utf-8", errors="replace"))
                except OSError:
                    pass
        except Exception:
            pass

        app_id = exe_tag or comm_tag or fallback_name
        wm_class = fallback_name or comm_tag or exe_tag
        if exe_tag and exe_tag.lower() not in wm_class.lower():
            app_id = f"{exe_tag} {comm_tag}".strip()
        pair = (app_id, wm_class)
        if len(self._sender_proc_cache) > 128:
            self._sender_proc_cache.clear()
        self._sender_proc_cache[sender] = pair
        return pair

    def _check_atspi_window_active(self, conn: Gio.DBusConnection, ws: str, wp: str) -> str | None:
        """Return window title if (ws, wp) currently has ATSPI_STATE_ACTIVE (bit 1), else None."""
        try:
            states = conn.call_sync(
                ws,
                wp,
                "org.a11y.atspi.Accessible",
                "GetState",
                None,
                GLib.VariantType("(au)"),
                Gio.DBusCallFlags.NONE,
                90,
                None,
            ).unpack()[0]
            # ATSPI_STATE_ACTIVE == 1 -> bit 1 in states[0]
            if not states or not (int(states[0]) & (1 << 1)):
                return None
            title = conn.call_sync(
                ws,
                wp,
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", ("org.a11y.atspi.Accessible", "Name")),
                GLib.VariantType("(v)"),
                Gio.DBusCallFlags.NONE,
                90,
                None,
            ).unpack()[0]
            return str(title or "")
        except Exception:
            return None

    def _via_atspi_bus(self) -> WindowInfo | None:
        """Pure-Gio Wayland/X11 active window tracker via AT-SPI2 Registry (works live without relogin)."""
        conn = self._ensure_a11y_bus()
        if conn is None:
            return None

        # 1. Sub-millisecond hot-path: check if previously focused window is still STATE_ACTIVE
        if self._active_atspi_win is not None:
            ws, wp, app_id, wm_class = self._active_atspi_win
            title = self._check_atspi_window_active(conn, ws, wp)
            if title is not None:
                return WindowInfo(app_id=app_id, wm_class=wm_class, title=title, backend="wayland-atspi")
            self._active_atspi_win = None

        # 2. Scan desktop applications for the newly active top-level window
        try:
            apps = conn.call_sync(
                "org.a11y.atspi.Registry",
                "/org/a11y/atspi/accessible/root",
                "org.a11y.atspi.Accessible",
                "GetChildren",
                None,
                GLib.VariantType("(a(so))"),
                Gio.DBusCallFlags.NONE,
                200,
                None,
            ).unpack()[0]
        except Exception:
            return None

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
                        90,
                        None,
                    ).unpack()[0]
                    or ""
                )
                # Skip gnome-shell chrome desktop actor unless it's a real dialog
                if app_name.lower() == "gnome-shell":
                    continue
                wins = conn.call_sync(
                    app_sender,
                    app_path,
                    "org.a11y.atspi.Accessible",
                    "GetChildren",
                    None,
                    GLib.VariantType("(a(so))"),
                    Gio.DBusCallFlags.NONE,
                    110,
                    None,
                ).unpack()[0]
                for ws, wp in wins[:16]:
                    title = self._check_atspi_window_active(conn, ws, wp)
                    if title is not None:
                        app_id, wm_class = self._resolve_a11y_sender_proc(conn, ws, app_name)
                        self._active_atspi_win = (ws, wp, app_id, wm_class)
                        return WindowInfo(
                            app_id=app_id,
                            wm_class=wm_class,
                            title=title,
                            backend="wayland-atspi",
                        )
            except Exception:
                continue
        return None

    def _via_gnome_introspect_windows(self) -> WindowInfo | None:
        bus = self._ensure_session_bus()
        if bus is None:
            return None
        try:
            res = bus.call_sync(
                "org.gnome.Shell.Introspect",
                "/org/gnome/Shell/Introspect",
                "org.gnome.Shell.Introspect",
                "GetWindows",
                None,
                GLib.VariantType("(a{ta{sv}})"),
                Gio.DBusCallFlags.NO_AUTO_START,
                80,
                None,
            )
            windows = res.unpack()[0]
            for _, props in windows.items():
                if props.get("has-focus"):
                    return WindowInfo(
                        app_id=str(props.get("app-id", "")),
                        wm_class=str(props.get("wm-class", "")),
                        title=str(props.get("title", "")),
                        backend="gnome-introspect",
                    )
        except Exception:
            pass
        return None

    def _via_hyprland(self) -> WindowInfo | None:
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return None
        try:
            proc = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True,
                text=True,
                timeout=0.08,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                cls = str(data.get("class", ""))
                title = str(data.get("title", ""))
                if cls or title:
                    return WindowInfo(app_id=cls, wm_class=cls, title=title, backend="hyprland")
        except Exception:
            pass
        return None

    def _x11_env(self) -> dict[str, str] | None:
        env = os.environ.copy()
        if not env.get("DISPLAY"):
            xsocks = sorted(glob.glob("/tmp/.X11-unix/X*"))
            if not xsocks:
                return None
            # Prefer :0 when present
            disp_nums = [s.rsplit("X", 1)[1] for s in xsocks if s.rsplit("X", 1)[1].isdigit()]
            if not disp_nums:
                return None
            chosen = "0" if "0" in disp_nums else disp_nums[0]
            env["DISPLAY"] = f":{chosen}"
        if not env.get("XAUTHORITY"):
            auths = sorted(glob.glob(f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"))
            if auths:
                env["XAUTHORITY"] = auths[0]
        return env

    def _via_xprop(self) -> WindowInfo | None:
        env = self._x11_env()
        if env is None:
            return None
        try:
            root = subprocess.run(
                ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                env=env,
                capture_output=True,
                text=True,
                timeout=0.08,
                check=False,
            )
            if root.returncode != 0 or "0x" not in root.stdout:
                return None
            win_id = root.stdout.strip().split()[-1].rstrip(",")
            if win_id in ("0x0", "0x00"):
                return None
            win = subprocess.run(
                ["xprop", "-id", win_id, "WM_CLASS", "_NET_WM_NAME"],
                env=env,
                capture_output=True,
                text=True,
                timeout=0.08,
                check=False,
            )
            wm_class = ""
            title = ""
            for line in win.stdout.splitlines():
                if "not found" in line or "no such atom" in line:
                    continue
                if "WM_CLASS" in line and "=" in line:
                    wm_class = line.split("=", 1)[1].replace('"', "").strip()
                elif "_NET_WM_NAME" in line and "=" in line:
                    title = line.split("=", 1)[1].replace('"', "").strip()
            if wm_class or title:
                return WindowInfo(app_id=wm_class, wm_class=wm_class, title=title, backend="xwayland-x11")
        except Exception:
            pass
        return None
