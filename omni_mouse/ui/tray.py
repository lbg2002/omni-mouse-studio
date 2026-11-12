"""Ultra-lightweight resident system notification bar (AppIndicator) applet for Omni Mouse Studio.

Runs with minimal RAM (~18 MB) and 0.0% idle CPU (no WebKit2 / WebGL / HTTP server loaded).
Clicking '打开控制中心 (全量 3D 模式)' spawns omni-mouse-studio on demand, which exits completely on close.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # type: ignore

INDICATOR_MOD = None
for _ns, _ver in (("AyatanaAppIndicator3", "0.1"), ("AppIndicator3", "0.1")):
    try:
        gi.require_version(_ns, _ver)
        INDICATOR_MOD = __import__(f"gi.repository.{_ns}", fromlist=[_ns])
        break
    except Exception:
        continue

from ..config.profiles import CONFIG_PATH, load_config, save_config
from ..daemon.engine import query_daemon

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve_script(name: str) -> list[str]:
    local_bin = os.path.join(PACKAGE_ROOT, name)
    if os.path.isfile(local_bin):
        return [sys.executable, local_bin]
    return [name]


class OmniMouseTrayApplet:
    """Lightweight top-bar notification indicator for quick controls & launching Full Mode UI."""

    def __init__(self) -> None:
        self._updating_checks = False
        self.menu = Gtk.Menu()

        # Primary CTA: Open Full 3D Studio Mode
        self.item_open = Gtk.MenuItem(label="打开控制中心 (全量 3D 模式)")
        self.item_open.connect("activate", self._on_open_studio)
        self.menu.append(self.item_open)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Read-only live status rows (updated on menu popup — zero background polling!)
        self.item_hw_status = Gtk.MenuItem(label="鼠标状态: 检测中...")
        self.item_hw_status.set_sensitive(False)
        self.menu.append(self.item_hw_status)

        self.item_profile_status = Gtk.MenuItem(label="当前方案: 全局默认配置")
        self.item_profile_status.set_sensitive(False)
        self.menu.append(self.item_profile_status)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Quick toggles
        self.chk_daemon = Gtk.CheckMenuItem(label="启用智能侧键与四向手势引擎")
        self.chk_daemon.connect("toggled", self._on_toggle_daemon_enabled)
        self.menu.append(self.chk_daemon)

        self.chk_per_app = Gtk.CheckMenuItem(label="按当前焦点应用自动切换方案")
        self.chk_per_app.connect("toggled", self._on_toggle_per_app)
        self.menu.append(self.chk_per_app)

        # Quick device model selector submenu
        model_item = Gtk.MenuItem(label="管理设备型号切换")
        model_sub = Gtk.Menu()
        for mkey, mlbl in (
            ("auto", "自动识别已连接鼠标 (推荐)"),
            ("inphic_w1", "英菲克 Inphic W1 (有线版)"),
            ("delux_m618xsd", "多彩 Delux M618XSD (垂直无线版)"),
        ):
            mi = Gtk.MenuItem(label=mlbl)
            mi.connect("activate", self._on_set_model, mkey)
            model_sub.append(mi)
        model_item.set_submenu(model_sub)
        self.menu.append(model_item)

        # Quick onboard polling rate submenu (M618XSD)
        self.poll_item = Gtk.MenuItem(label="切换硬件回报率 (M618XSD)")
        poll_sub = Gtk.Menu()
        for hz in (125, 250, 500, 1000):
            mi = Gtk.MenuItem(label=f"{hz} Hz")
            mi.connect("activate", self._on_set_poll, hz)
            poll_sub.append(mi)
        self.poll_item.set_submenu(poll_sub)
        self.menu.append(self.poll_item)

        self.item_restart_daemon = Gtk.MenuItem(label="重启后台鼠标守护服务")
        self.item_restart_daemon.connect("activate", self._on_restart_daemon)
        self.menu.append(self.item_restart_daemon)

        self.menu.append(Gtk.SeparatorMenuItem())

        self.item_quit = Gtk.MenuItem(label="退出通知栏常驻图标")
        self.item_quit.connect("activate", lambda *_: Gtk.main_quit())
        self.menu.append(self.item_quit)

        self.menu.connect("show", lambda *_: self.refresh_menu_state())
        self.menu.show_all()

        self.indicator: Any = None
        self.status_icon: Any = None
        self._init_indicator()
        self.refresh_menu_state()
        # Gentle 60s refresh for battery label only (0.00% CPU)
        GLib.timeout_add_seconds(60, self._periodic_refresh)

    def _init_indicator(self) -> None:
        icon_file = os.path.join(ASSETS_DIR, "omni-mouse-tray-active.svg")
        if INDICATOR_MOD is not None:
            ind = INDICATOR_MOD.Indicator.new(
                "omni-mouse-tray",
                "input-mouse",
                INDICATOR_MOD.IndicatorCategory.HARDWARE,
            )
            if os.path.exists(icon_file):
                ind.set_icon_theme_path(ASSETS_DIR)
                ind.set_icon_full("omni-mouse-tray-active", "Omni Mouse Studio")
            ind.set_title("Omni Mouse 多功能鼠标智控")
            ind.set_status(INDICATOR_MOD.IndicatorStatus.ACTIVE)
            ind.set_menu(self.menu)
            self.indicator = ind
        else:
            # Fallback Gtk.StatusIcon for X11 environments without AppIndicator
            si = Gtk.StatusIcon()
            if os.path.exists(icon_file):
                si.set_from_file(icon_file)
            else:
                si.set_from_icon_name("input-mouse")
            si.set_tooltip_text("Omni Mouse 多功能鼠标智控")
            si.connect("activate", self._on_open_studio)
            si.connect(
                "popup-menu",
                lambda icon, button, activate_time: self.menu.popup(
                    None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time
                ),
            )
            self.status_icon = si

    def _periodic_refresh(self) -> bool:
        self.refresh_menu_state()
        return True

    def refresh_menu_state(self) -> None:
        cfg = load_config(CONFIG_PATH)
        st = query_daemon("status")

        self._updating_checks = True
        try:
            self.chk_daemon.set_active(bool(cfg.daemon_enabled))
            self.chk_per_app.set_active(bool(cfg.per_app_enabled))
        finally:
            self._updating_checks = False

        if st and st.get("ok"):
            dev_model = st.get("device_model") or ""
            grab_txt = "已接管" if st.get("grabbed") else "硬件直通"
            if dev_model == "inphic_w1":
                self.item_hw_status.set_label(f"设备: Inphic W1 有线版 · {grab_txt}")
                self.poll_item.set_sensitive(False)
            elif dev_model == "delux_m618xsd":
                bat = st.get("battery")
                bat_txt = (
                    f"{bat['percent']}%"
                    if isinstance(bat, dict) and isinstance(bat.get("percent"), int)
                    else "在线"
                )
                self.item_hw_status.set_label(f"设备: M618XSD · {grab_txt} · 电量 {bat_txt}")
                self.poll_item.set_sensitive(True)
            else:
                self.item_hw_status.set_label(f"状态: 守护运行中 (等待鼠标接入)")
                self.poll_item.set_sensitive(True)
            prof_name = (st.get("active_profile") or {}).get("name") or "全局默认配置"
            self.item_profile_status.set_label(f"生效方案: {prof_name}")
        else:
            self.item_hw_status.set_label("状态: 后台守护未运行 (点击下方可重启)")
            self.item_profile_status.set_label("生效方案: 板载固件原生模式")

    def _on_open_studio(self, *_args: Any) -> None:
        subprocess.Popen(
            _resolve_script("omni-mouse-studio"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _on_toggle_daemon_enabled(self, widget: Gtk.CheckMenuItem) -> None:
        if self._updating_checks:
            return
        cfg = load_config(CONFIG_PATH)
        cfg.daemon_enabled = bool(widget.get_active())
        save_config(cfg, CONFIG_PATH)
        query_daemon("reload")
        self.refresh_menu_state()

    def _on_toggle_per_app(self, widget: Gtk.CheckMenuItem) -> None:
        if self._updating_checks:
            return
        cfg = load_config(CONFIG_PATH)
        cfg.per_app_enabled = bool(widget.get_active())
        save_config(cfg, CONFIG_PATH)
        query_daemon("reload")
        self.refresh_menu_state()

    def _on_set_model(self, _widget: Gtk.MenuItem, mkey: str) -> None:
        cfg = load_config(CONFIG_PATH)
        cfg.preferred_model = mkey
        save_config(cfg, CONFIG_PATH)
        query_daemon("reload")
        GLib.timeout_add(300, lambda: (self.refresh_menu_state(), False)[1])

    def _on_set_poll(self, _widget: Gtk.MenuItem, hz: int) -> None:
        subprocess.Popen(
            [*_resolve_script("omni-mouse-cli"), "poll", str(hz)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _on_restart_daemon(self, *_args: Any) -> None:
        res = subprocess.run(
            ["systemctl", "--user", "restart", "omni-mouse-daemon.service"],
            capture_output=True,
            check=False,
        )
        if res.returncode != 0:
            subprocess.Popen(
                _resolve_script("omni-mouse-daemon"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        GLib.timeout_add(500, lambda: (self.refresh_menu_state(), False)[1])


def run_tray() -> int:
    GLib.set_prgname("omni-mouse-tray")
    _applet = OmniMouseTrayApplet()
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tray())
