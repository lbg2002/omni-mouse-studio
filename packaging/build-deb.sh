#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.2.2"
PKG_NAME="omni-mouse-studio"
ARCH="all"
STAGE_DIR="$(mktemp -d)"
DIST_DIR="${PROJECT_ROOT}/dist"

cleanup() {
    rm -rf "${STAGE_DIR}"
}
trap cleanup EXIT

mkdir -p "${STAGE_DIR}/DEBIAN" \
         "${STAGE_DIR}/usr/lib/omni-mouse-studio" \
         "${STAGE_DIR}/usr/bin" \
         "${STAGE_DIR}/lib/udev/rules.d" \
         "${STAGE_DIR}/usr/lib/systemd/user" \
         "${STAGE_DIR}/usr/share/applications" \
         "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps" \
         "${STAGE_DIR}/etc/xdg/autostart" \
         "${DIST_DIR}"

# 1. Copy Python package & resources
cp -r "${PROJECT_ROOT}/omni_mouse" "${STAGE_DIR}/usr/lib/omni-mouse-studio/"
find "${STAGE_DIR}/usr/lib/omni-mouse-studio" -name "__pycache__" -type d -exec rm -rf {} +
cp -f "${PROJECT_ROOT}/factory_backup.json" "${STAGE_DIR}/usr/lib/omni-mouse-studio/"
cp -f "${PROJECT_ROOT}/omni-mouse-studio" \
      "${PROJECT_ROOT}/omni-mouse-daemon" \
      "${PROJECT_ROOT}/omni-mouse-tray" \
      "${PROJECT_ROOT}/omni-mouse-cli" \
      "${STAGE_DIR}/usr/lib/omni-mouse-studio/"
chmod 0755 "${STAGE_DIR}/usr/lib/omni-mouse-studio/omni-mouse-"*

# 2. /usr/bin symlinks
for cmd in omni-mouse-studio omni-mouse-daemon omni-mouse-tray omni-mouse-cli; do
    ln -sf "/usr/lib/omni-mouse-studio/${cmd}" "${STAGE_DIR}/usr/bin/${cmd}"
done

# 3. udev rules
cp -f "${PROJECT_ROOT}/udev/99-omni-mouse-studio.rules" "${STAGE_DIR}/lib/udev/rules.d/99-omni-mouse-studio.rules"

# 4. Systemd user units
for svc in omni-mouse-daemon.service omni-mouse-tray.service; do
    sed "s|__PROJECT_ROOT__|/usr/lib/omni-mouse-studio|g" \
        "${PROJECT_ROOT}/systemd/${svc}" \
        > "${STAGE_DIR}/usr/lib/systemd/user/${svc}"
done

# 5. Desktop entry, icon & XDG autostart for tray indicator
cp -f "${PROJECT_ROOT}/omni_mouse/ui/assets/omni-mouse-studio.svg" \
      "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps/omni-mouse-studio.svg"

cat > "${STAGE_DIR}/usr/share/applications/omni-mouse-studio.desktop" <<'EOF'
[Desktop Entry]
Name=Omni Mouse Studio
Name[zh_CN]=Omni Mouse 多功能鼠标智控中心
Comment=On-Demand 3D Hardware Driver, CPI/DPI, LED & Per-App Smart Remapper for Multi-Brand Mice
Comment[zh_CN]=支持英菲克 Inphic W1 与多彩 Delux M618XSD 的 3D 硬件驱动、CPI/DPI、灯效、侧键手势与按应用智控中心
Exec=/usr/bin/omni-mouse-studio
Icon=omni-mouse-studio
Terminal=false
Type=Application
Categories=Settings;HardwareSettings;Utility;
Keywords=mouse;omni;delux;m618xsd;inphic;w1;dpi;cpi;rgb;remapper;鼠标;多彩;英菲克;
StartupWMClass=omni-mouse-studio
EOF

cat > "${STAGE_DIR}/etc/xdg/autostart/omni-mouse-tray.desktop" <<'EOF'
[Desktop Entry]
Name=Omni Mouse Studio Tray Indicator
Name[zh_CN]=Omni Mouse 通知栏常驻托盘
Exec=/usr/bin/omni-mouse-tray
Icon=omni-mouse-studio
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
NoDisplay=true
EOF

# 6. Debian control & postinst scripts
cat > "${STAGE_DIR}/DEBIAN/control" <<EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1
Recommends: gir1.2-ayatanaappindicator3-0.1
Replaces: delux-m618xsd-driver
Conflicts: delux-m618xsd-driver
Maintainer: dugubaoguo <dugubaoguo@gmail.com>
Homepage: https://github.com/lbg2002/omni-mouse-studio
Description: Omni Mouse Studio - Multi-Device Linux Mouse Driver & 3D Control Center
 Native Linux multi-device mouse driver supporting both the Inphic W1 wired
 gaming mouse (Instant Microelectronics A704/A725) and the Delux M618XSD
 (Seeker) wireless/wired vertical ergonomic mouse. Features a zero-idle-CPU
 background per-app/gesture/side-wheel daemon, top-bar tray indicator, and an
 on-demand WebGL 3D control studio for CPI/DPI, LED modes, and button mapping.
EOF

cat > "${STAGE_DIR}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger --subsystem-match=hidraw || true
    udevadm trigger --subsystem-match=input || true
    udevadm trigger --name-match=uinput || true
fi
if [ -e /dev/uinput ]; then
    chmod 0660 /dev/uinput || true
fi
systemctl --global enable omni-mouse-daemon.service omni-mouse-tray.service 2>/dev/null || true
exit 0
EOF
chmod 0755 "${STAGE_DIR}" "${STAGE_DIR}/DEBIAN"
chmod 0755 "${STAGE_DIR}/DEBIAN/postinst"

DEB_OUT="${DIST_DIR}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "${STAGE_DIR}" "${DEB_OUT}"
echo "Built Debian package: ${DEB_OUT}"
