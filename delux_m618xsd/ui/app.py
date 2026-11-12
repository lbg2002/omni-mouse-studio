"""Native GTK3 + WebKit2 4.1 On-Demand Single-Instance Full-Mode Window for Delux M618XSD."""

from __future__ import annotations

import os
import signal
import sys

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # type: ignore

from .server import StudioBackendState, start_studio_server


class M618XSDStudioApp(Gtk.Application):
    """Single-instance on-demand Full Mode UI. Exits completely on window close to free 100% WebGL/WebKit RAM."""

    def __init__(self) -> None:
        super().__init__(
            application_id="com.delux.M618XSDStudio",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.backend: StudioBackendState | None = None
        self.server = None
        self.url: str = ""
        self.window: Gtk.ApplicationWindow | None = None
        self.webview: WebKit2.WebView | None = None

    def do_activate(self) -> None:  # noqa: N802
        if self.window is not None:
            self.window.present()
            return

        self.backend = StudioBackendState()
        self.server, self.url = start_studio_server(self.backend)
        win = self._build_window()
        win.show_all()
        win.present()

    def _build_window(self) -> Gtk.ApplicationWindow:
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-application-prefer-dark-theme", True)

        GLib.set_prgname("delux-m618xsd-studio")
        GLib.set_application_name("Linux 多功能鼠标智控中心")

        win = Gtk.ApplicationWindow(
            application=self,
            title="LINUX SMART MOUSE STUDIO // DELUX M618XSD & INPHIC W1",
        )
        win.set_default_size(1300, 820)
        win.set_size_request(980, 640)
        win.set_position(Gtk.WindowPosition.CENTER)

        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        for candidate in ("delux-m618xsd.svg", "m618xsd_right.png"):
            icon_path = os.path.join(assets_dir, candidate)
            if os.path.exists(icon_path):
                try:
                    win.set_icon_from_file(icon_path)
                    break
                except Exception:
                    pass

        wk_settings = WebKit2.Settings()
        for prop, val in (
            ("enable-webgl", True),
            ("enable-accelerated-2d-canvas", True),
            ("enable-smooth-scrolling", True),
            ("enable-developer-extras", False),
            ("enable-write-console-messages-to-stdout", False),
        ):
            try:
                wk_settings.set_property(prop, val)
            except Exception:
                pass

        ctx = WebKit2.WebContext.new()
        try:
            ctx.set_network_proxy_settings(WebKit2.NetworkProxyMode.NO_PROXY, None)
        except Exception:
            pass
        try:
            dm = ctx.get_website_data_manager()
            if hasattr(dm, "set_network_proxy_settings"):
                dm.set_network_proxy_settings(WebKit2.NetworkProxyMode.NO_PROXY, None)
        except Exception:
            pass

        webview = WebKit2.WebView.new_with_context(ctx)
        webview.set_settings(wk_settings)
        webview.set_background_color(Gdk.RGBA(0.035, 0.043, 0.055, 1.0))
        webview.connect("context-menu", lambda *_args: True)
        webview.connect(
            "notify::title",
            lambda wv, _pspec: win.set_title(wv.get_title() or "LINUX SMART MOUSE STUDIO"),
        )
        webview.load_uri(self.url)

        win.add(webview)
        win.connect("destroy", self._on_destroy)

        self.window = win
        self.webview = webview
        return win

    def _on_destroy(self, *_args) -> None:
        srv = self.server
        self.server = None
        self.window = None
        self.webview = None
        if srv is not None:
            try:
                srv.shutdown()
            except Exception:
                pass
        self.quit()


def run_gui() -> int:
    app = M618XSDStudioApp()
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    return int(app.run(sys.argv))


if __name__ == "__main__":
    raise SystemExit(run_gui())
