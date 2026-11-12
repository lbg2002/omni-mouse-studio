#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_ONLY="${1:-}"

chmod +x "${PROJECT_ROOT}/m618xsd-studio" \
         "${PROJECT_ROOT}/m618xsd-daemon" \
         "${PROJECT_ROOT}/m618xsd-tray" \
         "${PROJECT_ROOT}/m618xsd-cli" \
         "${PROJECT_ROOT}/udev/install-udev.sh"

# 1. Install udev permissions unless --user-only
if [ "${USER_ONLY}" != "--user-only" ]; then
    if ( [ ! -f /etc/udev/rules.d/99-delux-m618xsd.rules ] && [ ! -f /lib/udev/rules.d/99-delux-m618xsd.rules ] ) || ! grep -q "30fa" /etc/udev/rules.d/99-delux-m618xsd.rules /lib/udev/rules.d/99-delux-m618xsd.rules 2>/dev/null; then
        echo ">>> 安装/升级 udev 多型号鼠标访问权限规则..."
        pkexec "${PROJECT_ROOT}/udev/install-udev.sh"
    else
        echo ">>> 已检测到最新 udev 权限规则，跳过提权安装。"
    fi
fi

# 2. Install GNOME Shell Wayland Focus Helper extension
EXT_UUID="delux-focus@m618xsd"
EXT_DST="${HOME}/.local/share/gnome-shell/extensions/${EXT_UUID}"
mkdir -p "${EXT_DST}"
cp -f "${PROJECT_ROOT}/gnome-extension/${EXT_UUID}/metadata.json" "${EXT_DST}/metadata.json"
cp -f "${PROJECT_ROOT}/gnome-extension/${EXT_UUID}/extension.js" "${EXT_DST}/extension.js"
gnome-extensions enable "${EXT_UUID}" 2>/dev/null || true

# 3. Install Desktop Launcher & App Icon
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
mkdir -p "${ICON_DIR}"
cp -f "${PROJECT_ROOT}/delux_m618xsd/ui/assets/delux-m618xsd.svg" "${ICON_DIR}/delux-m618xsd.svg"

APP_DIR="${HOME}/.local/share/applications"
mkdir -p "${APP_DIR}"
sed "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" \
    "${PROJECT_ROOT}/desktop/delux-m618xsd-studio.desktop" \
    > "${APP_DIR}/delux-m618xsd-studio.desktop"
chmod +x "${APP_DIR}/delux-m618xsd-studio.desktop"

# 4. Install ~/.local/bin symlinks for CLI, Daemon, Tray & Studio
BIN_DIR="${HOME}/.local/bin"
mkdir -p "${BIN_DIR}"
for cmd in m618xsd-studio m618xsd-daemon m618xsd-tray m618xsd-cli; do
    ln -sf "${PROJECT_ROOT}/${cmd}" "${BIN_DIR}/${cmd}"
done

# 5. Install & enable systemd --user minimal background daemon + top-bar tray service
SYS_USER_DIR="${HOME}/.config/systemd/user"
mkdir -p "${SYS_USER_DIR}"
for svc in delux-m618xsd-daemon.service delux-m618xsd-tray.service; do
    sed "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" \
        "${PROJECT_ROOT}/systemd/${svc}" \
        > "${SYS_USER_DIR}/${svc}"
done

systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now delux-m618xsd-daemon.service 2>/dev/null || true
systemctl --user enable --now delux-m618xsd-tray.service 2>/dev/null || true

echo "============================================================"
echo "Delux M618XSD Linux 驱动安装完成！"
echo "  - 后台极简守护服务: delux-m618xsd-daemon.service (0% 空闲 CPU)"
echo "  - 顶部通知栏常驻托盘: delux-m618xsd-tray.service (点击可按需打开全量 3D 界面)"
echo "  - 按需全量控制中心: m618xsd-studio (关闭窗口后自动释放全部 3D/WebKit 内存)"
echo "============================================================"
