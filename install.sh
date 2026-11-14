#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_ONLY="${1:-}"

chmod +x "${PROJECT_ROOT}/omni-mouse-studio" \
         "${PROJECT_ROOT}/omni-mouse-daemon" \
         "${PROJECT_ROOT}/omni-mouse-tray" \
         "${PROJECT_ROOT}/omni-mouse-cli" \
         "${PROJECT_ROOT}/udev/install-udev.sh"

# 1. Install udev permissions unless --user-only
if [ "${USER_ONLY}" != "--user-only" ]; then
    UDEV_FILES=(/etc/udev/rules.d/70-omni-mouse-studio.rules /lib/udev/rules.d/70-omni-mouse-studio.rules)
    if ! grep -q 'GROUP="plugdev"' "${UDEV_FILES[@]}" 2>/dev/null; then
        echo ">>> 安装/升级 Omni Mouse Studio 70-udev 持久设备权限规则..."
        pkexec "${PROJECT_ROOT}/udev/install-udev.sh"
    else
        echo ">>> 已检测到最新 70-udev 权限规则，跳过提权安装。"
    fi
fi

# 2. Clean up legacy delux-m618xsd user services & launchers if upgrading
systemctl --user disable --now delux-m618xsd-tray.service delux-m618xsd-daemon.service 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/delux-m618xsd-tray.service" \
      "${HOME}/.config/systemd/user/delux-m618xsd-daemon.service" \
      "${HOME}/.local/share/applications/delux-m618xsd-studio.desktop" \
      "${HOME}/.local/share/icons/hicolor/scalable/apps/delux-m618xsd.svg" \
      "${HOME}/.local/bin/m618xsd-studio" \
      "${HOME}/.local/bin/m618xsd-daemon" \
      "${HOME}/.local/bin/m618xsd-tray" \
      "${HOME}/.local/bin/m618xsd-cli"

if [ -d "${HOME}/.config/delux-m618xsd" ] && [ ! -d "${HOME}/.config/omni-mouse-studio" ]; then
    cp -a "${HOME}/.config/delux-m618xsd" "${HOME}/.config/omni-mouse-studio"
    rm -f "${HOME}/.config/omni-mouse-studio/daemon.sock"
fi

# 3. Install GNOME Shell Wayland Focus Helper extension
EXT_UUID="omni-focus@omni-mouse"
EXT_DST="${HOME}/.local/share/gnome-shell/extensions/${EXT_UUID}"
mkdir -p "${EXT_DST}"
cp -f "${PROJECT_ROOT}/gnome-extension/${EXT_UUID}/metadata.json" "${EXT_DST}/metadata.json"
cp -f "${PROJECT_ROOT}/gnome-extension/${EXT_UUID}/extension.js" "${EXT_DST}/extension.js"
gnome-extensions enable "${EXT_UUID}" 2>/dev/null || true

# 4. Install Desktop Launcher & App Icon
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
mkdir -p "${ICON_DIR}"
cp -f "${PROJECT_ROOT}/omni_mouse/ui/assets/omni-mouse-studio.svg" "${ICON_DIR}/omni-mouse-studio.svg"

APP_DIR="${HOME}/.local/share/applications"
mkdir -p "${APP_DIR}"
sed "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" \
    "${PROJECT_ROOT}/desktop/omni-mouse-studio.desktop" \
    > "${APP_DIR}/omni-mouse-studio.desktop"
chmod +x "${APP_DIR}/omni-mouse-studio.desktop"

# 5. Install ~/.local/bin symlinks for CLI, Daemon, Tray & Studio
BIN_DIR="${HOME}/.local/bin"
mkdir -p "${BIN_DIR}"
for cmd in omni-mouse-studio omni-mouse-daemon omni-mouse-tray omni-mouse-cli; do
    ln -sf "${PROJECT_ROOT}/${cmd}" "${BIN_DIR}/${cmd}"
done

# 6. Install & enable systemd --user minimal background daemon + top-bar tray service
SYS_USER_DIR="${HOME}/.config/systemd/user"
mkdir -p "${SYS_USER_DIR}"
for svc in omni-mouse-daemon.service omni-mouse-tray.service; do
    sed "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" \
        "${PROJECT_ROOT}/systemd/${svc}" \
        > "${SYS_USER_DIR}/${svc}"
done

systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now omni-mouse-daemon.service 2>/dev/null || true
systemctl --user enable --now omni-mouse-tray.service 2>/dev/null || true

echo "============================================================"
echo "Omni Mouse Studio 安装完成！"
echo "  - 后台极简守护服务: omni-mouse-daemon.service (0% 空闲 CPU)"
echo "  - 顶部通知栏常驻托盘: omni-mouse-tray.service (点击可按需打开全量 3D 界面)"
echo "  - 按需全量控制中心: omni-mouse-studio (关闭窗口后自动释放全部 3D/WebKit 内存)"
echo "============================================================"
