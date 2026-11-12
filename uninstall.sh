#!/bin/bash
set -euo pipefail

echo ">>> 停止并移除用户态常驻服务..."
systemctl --user disable --now omni-mouse-tray.service omni-mouse-daemon.service 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/omni-mouse-tray.service" \
      "${HOME}/.config/systemd/user/omni-mouse-daemon.service"
systemctl --user daemon-reload 2>/dev/null || true

echo ">>> 移除桌面启动器与命令行软链接..."
rm -f "${HOME}/.local/share/applications/omni-mouse-studio.desktop" \
      "${HOME}/.local/share/icons/hicolor/scalable/apps/omni-mouse-studio.svg" \
      "${HOME}/.local/bin/omni-mouse-studio" \
      "${HOME}/.local/bin/omni-mouse-daemon" \
      "${HOME}/.local/bin/omni-mouse-tray" \
      "${HOME}/.local/bin/omni-mouse-cli"

echo "卸载完成（个人配置文件保留在 ~/.config/omni-mouse-studio/，如需彻底清理可手动删除）。"
