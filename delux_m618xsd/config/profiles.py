"""Persistent configuration and Per-Application profile rules for Delux M618XSD Studio."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

CONFIG_DIR = os.path.expanduser("~/.config/delux-m618xsd")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
IPC_SOCKET_PATH = os.path.join(CONFIG_DIR, "daemon.sock")

# Supported logical inputs in the smart daemon
BINDABLE_INPUTS: dict[str, str] = {
    "forward": "前进侧键 (Forward)",
    "backward": "后退侧键 (Backward)",
    "middle": "滚轮中键 (Middle Click)",
    "thumb_up": "拇指侧滚轮 · 上拨",
    "thumb_down": "拇指侧滚轮 · 下拨",
}

# Curated quick-select presets for the UI dropdowns
ACTION_PRESETS: list[tuple[str, str, dict[str, Any]]] = [
    ("passthrough", "保持原厂默认功能", {"kind": "passthrough"}),
    ("disabled", "禁用此按键/滚轮", {"kind": "disabled"}),
    ("tab_next", "切换下一标签页 (Ctrl+Tab)", {"kind": "key_combo", "combo": "Ctrl+Tab"}),
    ("tab_prev", "切换上一标签页 (Ctrl+Shift+Tab)", {"kind": "key_combo", "combo": "Ctrl+Shift+Tab"}),
    ("tab_pgdn", "下一标签页 (Ctrl+PageDown)", {"kind": "key_combo", "combo": "Ctrl+PageDown"}),
    ("tab_pgup", "上一标签页 (Ctrl+PageUp)", {"kind": "key_combo", "combo": "Ctrl+PageUp"}),
    ("close_tab", "关闭当前标签页 (Ctrl+W)", {"kind": "key_combo", "combo": "Ctrl+W"}),
    ("reopen_tab", "恢复关闭的标签页 (Ctrl+Shift+T)", {"kind": "key_combo", "combo": "Ctrl+Shift+T"}),
    ("copy", "复制 (Ctrl+C)", {"kind": "key_combo", "combo": "Ctrl+C"}),
    ("paste", "粘贴 (Ctrl+V)", {"kind": "key_combo", "combo": "Ctrl+V"}),
    ("term_copy", "终端复制 (Ctrl+Shift+C)", {"kind": "key_combo", "combo": "Ctrl+Shift+C"}),
    ("term_paste", "终端粘贴 (Ctrl+Shift+V)", {"kind": "key_combo", "combo": "Ctrl+Shift+V"}),
    ("undo", "撤销 (Ctrl+Z)", {"kind": "key_combo", "combo": "Ctrl+Z"}),
    ("redo", "重做 (Ctrl+Shift+Z)", {"kind": "key_combo", "combo": "Ctrl+Shift+Z"}),
    ("overview", "GNOME 工作区活动概览 (Super)", {"kind": "key_combo", "combo": "Super"}),
    ("ws_prev", "切换上一工作区 (Super+PageUp)", {"kind": "key_combo", "combo": "Super+PageUp"}),
    ("ws_next", "切换下一工作区 (Super+PageDown)", {"kind": "key_combo", "combo": "Super+PageDown"}),
    ("minimize", "最小化当前窗口 (Super+H)", {"kind": "key_combo", "combo": "Super+H"}),
    ("zoom_in", "智能画面放大 (自动适配图片/PDF/WPS/设计)", {"kind": "zoom", "direction": 1, "zoom_mode": "auto"}),
    ("zoom_out", "智能画面缩小 (自动适配图片/PDF/WPS/设计)", {"kind": "zoom", "direction": -1, "zoom_mode": "auto"}),
    ("zoom_key_in", "快捷键放大 (Ctrl + =)", {"kind": "zoom", "direction": 1, "zoom_mode": "keys"}),
    ("zoom_key_out", "快捷键缩小 (Ctrl + -)", {"kind": "zoom", "direction": -1, "zoom_mode": "keys"}),
    ("zoom_wheel_in", "滚轮放大 (Ctrl + 滚轮上)", {"kind": "zoom", "direction": 1, "zoom_mode": "wheel"}),
    ("zoom_wheel_out", "滚轮缩小 (Ctrl + 滚轮下)", {"kind": "zoom", "direction": -1, "zoom_mode": "wheel"}),
    ("vol_up", "系统音量 +", {"kind": "media", "media": "VOLUMEUP"}),
    ("vol_down", "系统音量 -", {"kind": "media", "media": "VOLUMEDOWN"}),
    ("vol_mute", "静音切换", {"kind": "media", "media": "MUTE"}),
    ("play_pause", "媒体播放 / 暂停", {"kind": "media", "media": "PLAYPAUSE"}),
    ("next_song", "下一曲", {"kind": "media", "media": "NEXTSONG"}),
    ("prev_song", "上一曲", {"kind": "media", "media": "PREVIOUSSONG"}),
    ("arrow_left", "方向键 ← (时间轴/光标左移)", {"kind": "key_combo", "combo": "Left"}),
    ("arrow_right", "方向键 → (时间轴/光标右移)", {"kind": "key_combo", "combo": "Right"}),
    ("page_up", "向上翻页 (PageUp)", {"kind": "key_combo", "combo": "PageUp"}),
    ("page_down", "向下翻页 (PageDown)", {"kind": "key_combo", "combo": "PageDown"}),
    ("hscroll_left", "横向左滚 (平滑倍速)", {"kind": "scroll", "axis": "h", "step": -1}),
    ("hscroll_right", "横向右滚 (平滑倍速)", {"kind": "scroll", "axis": "h", "step": 1}),
    ("sniper", "按住精准微操模式 (0.4x 灵敏度)", {"kind": "sniper_dpi", "scale": 0.4}),
    ("screenshot", "交互式截图 (PrintScreen)", {"kind": "key_combo", "combo": "PrintScreen"}),
]


@dataclass
class ActionSpec:
    """Action bound to a button, wheel direction, or gesture direction.

    Supported ``kind`` values:
    - ``passthrough``: emit native mouse button / wheel event
    - ``disabled``: swallow event
    - ``key_combo``: press & release ``combo`` (e.g. ``"Ctrl+Shift+Tab"``)
    - ``media``: press & release ``media`` EV_KEY name (e.g. ``"VOLUMEUP"``)
    - ``zoom``: hold LeftCtrl + vertical wheel ``direction`` (+1 or -1)
    - ``scroll``: emit wheel along ``axis`` ('v' or 'h') * ``step``
    - ``sniper_dpi``: while held, multiply pointer X/Y movement by ``scale``
    - ``command``: execute ``command`` asynchronously via /bin/sh
    - ``gesture_4way``: tap performs ``tap``, hold+slide triggers ``up``/``down``/``left``/``right``,
      and hold+main-wheel triggers ``wheel_up``/``wheel_down``!
    """

    kind: str = "passthrough"
    combo: str = ""
    media: str = ""
    direction: int = 1
    zoom_mode: str = "auto"
    axis: str = "h"
    step: int = 1
    scale: float = 0.4
    command: str = ""
    macro_steps: list[dict[str, Any]] | None = None
    gesture_threshold: int = 45
    tap: dict[str, Any] | None = None
    up: dict[str, Any] | None = None
    down: dict[str, Any] | None = None
    left: dict[str, Any] | None = None
    right: dict[str, Any] | None = None
    wheel_up: dict[str, Any] | None = None
    wheel_down: dict[str, Any] | None = None

    def summary(self) -> str:
        if self.kind == "passthrough":
            return "默认功能"
        if self.kind == "disabled":
            return "已禁用"
        if self.kind == "key_combo":
            return f"快捷键: {self.combo}"
        if self.kind == "media":
            labels = {
                "VOLUMEUP": "音量 +",
                "VOLUMEDOWN": "音量 -",
                "MUTE": "静音",
                "PLAYPAUSE": "播放/暂停",
                "NEXTSONG": "下一曲",
                "PREVIOUSSONG": "上一曲",
            }
            return f"媒体: {labels.get(self.media, self.media)}"
        if self.kind == "zoom":
            act = "放大" if self.direction > 0 else "缩小"
            if self.zoom_mode == "keys":
                return f"快捷键{act} (Ctrl+{'=' if self.direction > 0 else '-'})"
            if self.zoom_mode == "wheel":
                return f"滚轮{act} (Ctrl+滚轮{'上' if self.direction > 0 else '下'})"
            return f"智能画面{act} (自适应应用)"
        if self.kind == "scroll":
            axis_lbl = "横向" if self.axis == "h" else "纵向"
            return f"{axis_lbl}滚动 ({self.step:+d})"
        if self.kind == "sniper_dpi":
            return f"按住微操 ({self.scale:.2f}x 速度)"
        if self.kind == "command":
            return f"运行命令: {self.command}"
        if self.kind == "macro":
            cnt = len(self.macro_steps or [])
            preview = " → ".join(str(s.get("combo", "")) for s in (self.macro_steps or [])[:3] if s.get("combo"))
            return f"宏序列 ({cnt}步: {preview})" if preview else f"宏序列 ({cnt}步)"
        if self.kind == "gesture_4way":
            tap_lbl = ActionSpec.from_dict(self.tap or {"kind": "passthrough"}).summary()
            return f"四向手势键 + 滚轮弦 (单击: {tap_lbl})"
        return self.kind

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind}
        if self.kind == "key_combo":
            out["combo"] = self.combo
        elif self.kind == "media":
            out["media"] = self.media
        elif self.kind == "zoom":
            out["direction"] = self.direction
            if self.zoom_mode and self.zoom_mode != "auto":
                out["zoom_mode"] = self.zoom_mode
        elif self.kind == "scroll":
            out["axis"] = self.axis
            out["step"] = self.step
        elif self.kind == "sniper_dpi":
            out["scale"] = self.scale
        elif self.kind == "command":
            out["command"] = self.command
        elif self.kind == "macro":
            out["macro_steps"] = list(self.macro_steps or [])
        elif self.kind == "gesture_4way":
            out["gesture_threshold"] = self.gesture_threshold
            for sub in ("tap", "up", "down", "left", "right", "wheel_up", "wheel_down"):
                val = getattr(self, sub)
                if val is not None:
                    out[sub] = val
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ActionSpec":
        if not data:
            return cls()
        return cls(
            kind=str(data.get("kind", "passthrough")),
            combo=str(data.get("combo", "")),
            media=str(data.get("media", "")),
            direction=int(data.get("direction", 1)),
            zoom_mode=str(data.get("zoom_mode", "auto")),
            axis=str(data.get("axis", "h")),
            step=int(data.get("step", 1)),
            scale=float(data.get("scale", 0.4)),
            command=str(data.get("command", "")),
            macro_steps=data.get("macro_steps"),
            gesture_threshold=int(data.get("gesture_threshold", 45)),
            tap=data.get("tap"),
            up=data.get("up"),
            down=data.get("down"),
            left=data.get("left"),
            right=data.get("right"),
            wheel_up=data.get("wheel_up"),
            wheel_down=data.get("wheel_down"),
        )


def _default_gesture_backward() -> ActionSpec:
    return ActionSpec(
        kind="gesture_4way",
        gesture_threshold=45,
        tap={"kind": "passthrough"},
        up={"kind": "key_combo", "combo": "Super"},
        down={"kind": "key_combo", "combo": "Super+H"},
        left={"kind": "key_combo", "combo": "Super+PageUp"},
        right={"kind": "key_combo", "combo": "Super+PageDown"},
        wheel_up={"kind": "media", "media": "VOLUMEUP"},
        wheel_down={"kind": "media", "media": "VOLUMEDOWN"},
    )


@dataclass
class AppProfile:
    id: str
    name: str
    enabled: bool = True
    is_global: bool = False
    match_patterns: list[str] = field(default_factory=list)
    pointer_scale: float = 1.0
    thumb_speed: float = 1.5
    thumb_invert: bool = False
    wheel_invert: bool = False
    bindings: dict[str, ActionSpec] = field(default_factory=dict)

    def get_binding(self, slot_key: str) -> ActionSpec:
        return self.bindings.get(slot_key, ActionSpec())

    def matches(self, app_id: str, wm_class: str, title: str) -> bool:
        if not self.enabled or self.is_global:
            return False
        haystack = f"{app_id} {wm_class} {title}".lower()
        for pat in self.match_patterns:
            p = pat.strip().lower()
            if p and p in haystack:
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "is_global": self.is_global,
            "match_patterns": list(self.match_patterns),
            "pointer_scale": self.pointer_scale,
            "thumb_speed": self.thumb_speed,
            "thumb_invert": self.thumb_invert,
            "wheel_invert": self.wheel_invert,
            "bindings": {k: v.to_dict() for k, v in self.bindings.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppProfile":
        raw_bindings = data.get("bindings") or {}
        bindings = {k: ActionSpec.from_dict(v) for k, v in raw_bindings.items()}
        for k in BINDABLE_INPUTS:
            bindings.setdefault(k, ActionSpec())
        return cls(
            id=str(data.get("id", "custom")),
            name=str(data.get("name", "自定义应用")),
            enabled=bool(data.get("enabled", True)),
            is_global=bool(data.get("is_global", False)),
            match_patterns=[str(x) for x in data.get("match_patterns", [])],
            pointer_scale=float(data.get("pointer_scale", 1.0)),
            thumb_speed=float(data.get("thumb_speed", 1.5)),
            thumb_invert=bool(data.get("thumb_invert", False)),
            wheel_invert=bool(data.get("wheel_invert", False)),
            bindings=bindings,
        )


def build_default_profiles() -> list[AppProfile]:
    global_prof = AppProfile(
        id="global",
        name="全局默认配置 (所有桌面环境通用)",
        enabled=True,
        is_global=True,
        match_patterns=[],
        pointer_scale=1.0,
        thumb_speed=1.5,
        bindings={
            "forward": ActionSpec("passthrough"),
            "backward": _default_gesture_backward(),
            "middle": ActionSpec("passthrough"),
            "thumb_up": ActionSpec("passthrough"),
            "thumb_down": ActionSpec("passthrough"),
        },
    )

    browser_prof = AppProfile(
        id="browsers",
        name="网页浏览器 (Chrome / Edge / Firefox)",
        enabled=True,
        match_patterns=["chrome", "chromium", "firefox", "microsoft-edge", "brave", "opera", "vivaldi"],
        pointer_scale=1.0,
        thumb_speed=1.0,
        bindings={
            "forward": ActionSpec("passthrough"),
            "backward": _default_gesture_backward(),
            "middle": ActionSpec("passthrough"),
            "thumb_up": ActionSpec(kind="key_combo", combo="Ctrl+Shift+Tab"),
            "thumb_down": ActionSpec(kind="key_combo", combo="Ctrl+Tab"),
        },
    )

    ide_prof = AppProfile(
        id="code_ide",
        name="代码编辑器与 IDE (VS Code / Antigravity / JetBrains)",
        enabled=True,
        match_patterns=["code", "antigravity", "vscodium", "jetbrains", "pycharm", "idea", "clion", "goland", "cursor", "zed"],
        pointer_scale=1.0,
        thumb_speed=2.0,
        bindings={
            "forward": ActionSpec("passthrough"),
            "backward": _default_gesture_backward(),
            "middle": ActionSpec("passthrough"),
            "thumb_up": ActionSpec("passthrough"),
            "thumb_down": ActionSpec("passthrough"),
        },
    )

    viewer_prof = AppProfile(
        id="pdf_design",
        name="PDF 阅读与图片查看 (文档查看器 / 图片查看器 / WPS PDF / 设计)",
        enabled=True,
        match_patterns=[
            "loupe",
            "图像查看器",
            "图片查看器",
            "papers",
            "evince",
            "文档查看器",
            "okular",
            "wpspdf",
            "wps pdf",
            ".pdf - wps",
            "pdfarranger",
            "eog",
            "shotwell",
            "gthumb",
            "gimp",
            "inkscape",
            "krita",
        ],
        pointer_scale=1.0,
        thumb_speed=1.0,
        bindings={
            "forward": ActionSpec("passthrough"),
            "backward": _default_gesture_backward(),
            "middle": ActionSpec("passthrough"),
            "thumb_up": ActionSpec(kind="zoom", direction=1, zoom_mode="auto"),
            "thumb_down": ActionSpec(kind="zoom", direction=-1, zoom_mode="auto"),
        },
    )

    wps_prof = AppProfile(
        id="wps_office",
        name="WPS 办公与表格套件 (WPS 文字 / 表格 / 演示 / LibreOffice)",
        enabled=True,
        match_patterns=["wps", "et", "wpp", "libreoffice", "soffice"],
        pointer_scale=1.0,
        thumb_speed=1.8,
        bindings={
            "forward": ActionSpec("passthrough"),
            "backward": _default_gesture_backward(),
            "middle": ActionSpec("passthrough"),
            "thumb_up": ActionSpec("passthrough"),
            "thumb_down": ActionSpec("passthrough"),
        },
    )

    terminal_prof = AppProfile(
        id="terminal",
        name="终端模拟器 (GNOME Terminal / Ptyxis / Kitty)",
        enabled=False,  # Available as 1-click toggle so default terminal behavior isn't surprising
        match_patterns=["gnome-terminal", "ptyxis", "kgx", "kitty", "alacritty", "wezterm", "konsole", "terminator"],
        pointer_scale=1.0,
        thumb_speed=1.0,
        bindings={
            "forward": ActionSpec(kind="key_combo", combo="Ctrl+Shift+V"),
            "backward": ActionSpec(kind="key_combo", combo="Ctrl+Shift+C"),
            "middle": ActionSpec("passthrough"),
            "thumb_up": ActionSpec(kind="key_combo", combo="Ctrl+PageUp"),
            "thumb_down": ActionSpec(kind="key_combo", combo="Ctrl+PageDown"),
        },
    )

    return [global_prof, browser_prof, viewer_prof, wps_prof, ide_prof, terminal_prof]


@dataclass
class DriverConfig:
    daemon_enabled: bool = True
    per_app_enabled: bool = True
    preferred_model: str = "auto"
    profiles: list[AppProfile] = field(default_factory=build_default_profiles)

    @property
    def global_profile(self) -> AppProfile:
        for p in self.profiles:
            if p.is_global:
                return p
        g = build_default_profiles()[0]
        self.profiles.insert(0, g)
        return g

    def resolve_profile(self, app_id: str, wm_class: str, title: str) -> AppProfile:
        if self.per_app_enabled:
            for prof in self.profiles:
                if prof.matches(app_id, wm_class, title):
                    return prof
        return self.global_profile

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 2,
            "daemon_enabled": self.daemon_enabled,
            "per_app_enabled": self.per_app_enabled,
            "preferred_model": self.preferred_model,
            "profiles": [p.to_dict() for p in self.profiles],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DriverConfig":
        raw_profs = data.get("profiles")
        profs = [AppProfile.from_dict(item) for item in raw_profs] if raw_profs else build_default_profiles()
        if not any(p.is_global for p in profs):
            profs.insert(0, build_default_profiles()[0])
        pref = str(data.get("preferred_model", "auto") or "auto")
        if pref not in ("auto", "delux_m618xsd", "inphic_w1"):
            pref = "auto"
        return cls(
            daemon_enabled=bool(data.get("daemon_enabled", True)),
            per_app_enabled=bool(data.get("per_app_enabled", True)),
            preferred_model=pref,
            profiles=profs,
        )


def load_config(path: str = CONFIG_PATH) -> DriverConfig:
    if not os.path.exists(path):
        cfg = DriverConfig()
        save_config(cfg, path)
        return cfg
    try:
        with open(path, encoding="utf-8") as fh:
            return DriverConfig.from_dict(json.load(fh))
    except Exception:
        return DriverConfig()


def save_config(cfg: DriverConfig, path: str = CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg.to_dict(), fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
