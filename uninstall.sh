#!/bin/bash
set -euo pipefail

echo ">>> 停止并移除用户态常驻服务..."
systemctl --user disable --now delux-m618xsd-tray.service 2>/dev/null || true
systemctl --user disable --now delux-m618xsd-daemon.service 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/delux-m618xsd-tray.service" \
      "${HOME}/.config/systemd/user/delux-m618xsd-daemon.service"
systemctl --user daemon-reload 2>/dev/null || true

echo ">>> 移除桌面启动器与命令行软链接..."
rm -f "${HOME}/.local/share/applications/delux-m618xsd-studio.desktop" \
      "${HOME}/.local/share/icons/hicolor/scalable/apps/delux-m618xsd.svg" \
      "${HOME}/.local/bin/m618xsd-studio" \
      "${HOME}/.local/bin/m618xsd-daemon" \
      "${HOME}/.local/bin/m618xsd-tray" \
      "${HOME}/.local/bin/m618xsd-cli"

echo "卸载完成（个人配置文件保留在 ~/.config/delux-m618xsd/，如需彻底清理可手动删除）。"
