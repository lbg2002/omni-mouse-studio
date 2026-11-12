#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.1.0"
PKG_NAME="delux-m618xsd-driver"
ARCH="all"
STAGE_DIR="$(mktemp -d)"
DIST_DIR="${PROJECT_ROOT}/dist"

cleanup() {
    rm -rf "${STAGE_DIR}"
}
trap cleanup EXIT

mkdir -p "${STAGE_DIR}/DEBIAN" \
         "${STAGE_DIR}/usr/lib/delux-m618xsd" \
         "${STAGE_DIR}/usr/bin" \
         "${STAGE_DIR}/lib/udev/rules.d" \
         "${STAGE_DIR}/usr/lib/systemd/user" \
         "${STAGE_DIR}/usr/share/applications" \
         "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps" \
         "${STAGE_DIR}/etc/xdg/autostart" \
         "${DIST_DIR}"

# 1. Copy Python package & resources
cp -r "${PROJECT_ROOT}/delux_m618xsd" "${STAGE_DIR}/usr/lib/delux-m618xsd/"
find "${STAGE_DIR}/usr/lib/delux-m618xsd" -name "__pycache__" -type d -exec rm -rf {} +
cp -f "${PROJECT_ROOT}/factory_backup.json" "${STAGE_DIR}/usr/lib/delux-m618xsd/"
cp -f "${PROJECT_ROOT}/m618xsd-studio" \
      "${PROJECT_ROOT}/m618xsd-daemon" \
      "${PROJECT_ROOT}/m618xsd-tray" \
      "${PROJECT_ROOT}/m618xsd-cli" \
      "${STAGE_DIR}/usr/lib/delux-m618xsd/"
chmod 0755 "${STAGE_DIR}/usr/lib/delux-m618xsd/m618xsd-"*

# 2. /usr/bin symlinks
for cmd in m618xsd-studio m618xsd-daemon m618xsd-tray m618xsd-cli; do
    ln -sf "/usr/lib/delux-m618xsd/${cmd}" "${STAGE_DIR}/usr/bin/${cmd}"
done

# 3. udev rules
cp -f "${PROJECT_ROOT}/udev/99-delux-m618xsd.rules" "${STAGE_DIR}/lib/udev/rules.d/99-delux-m618xsd.rules"

# 4. Systemd user units
for svc in delux-m618xsd-daemon.service delux-m618xsd-tray.service; do
    sed "s|__PROJECT_ROOT__|/usr/lib/delux-m618xsd|g" \
        "${PROJECT_ROOT}/systemd/${svc}" \
        > "${STAGE_DIR}/usr/lib/systemd/user/${svc}"
done

# 5. Desktop entry, icon & XDG autostart for tray indicator
cp -f "${PROJECT_ROOT}/delux_m618xsd/ui/assets/delux-m618xsd.svg" \
      "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps/delux-m618xsd.svg"

cat > "${STAGE_DIR}/usr/share/applications/delux-m618xsd-studio.desktop" <<'EOF'
[Desktop Entry]
Name=Multi-Mouse 3D Control Center (Delux / Inphic)
Name[zh_CN]=多功能鼠标智控中心 (多彩 / 英菲克)
Comment=On-Demand 3D Hardware Driver, CPI/DPI, LED & Per-App Smart Remapper for Delux M618XSD & Inphic W1
Comment[zh_CN]=支持多彩 M618XSD 与英菲克 Inphic W1 的 3D 硬件驱动、CPI/DPI、灯效、侧键手势与按应用智能配置中心
Exec=/usr/bin/m618xsd-studio
Icon=delux-m618xsd
Terminal=false
Type=Application
Categories=Settings;HardwareSettings;Utility;
Keywords=mouse;delux;m618xsd;inphic;w1;dpi;cpi;rgb;remapper;鼠标;多彩;英菲克;
StartupWMClass=delux-m618xsd-studio
EOF

cat > "${STAGE_DIR}/etc/xdg/autostart/delux-m618xsd-tray.desktop" <<'EOF'
[Desktop Entry]
Name=Multi-Mouse Tray Indicator (Delux / Inphic)
Name[zh_CN]=多功能鼠标通知栏常驻托盘
Exec=/usr/bin/m618xsd-tray
Icon=delux-m618xsd
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
Maintainer: dugubaoguo <dugubaoguo@gmail.com>
Homepage: https://github.com/lbg2002/delux-m618xsd-driver
Description: Multi-Mouse Linux Hardware Driver & 3D Smart Control Center (Delux M618XSD & Inphic W1)
 Native Linux multi-device mouse driver supporting both the Delux M618XSD
 (Seeker) wireless/wired vertical ergonomic mouse and the Inphic W1 wired
 gaming mouse (Instant Microelectronics A704/A725). Features a zero-idle-CPU
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
systemctl --global enable delux-m618xsd-daemon.service delux-m618xsd-tray.service 2>/dev/null || true
exit 0
EOF
chmod 0755 "${STAGE_DIR}" "${STAGE_DIR}/DEBIAN"
chmod 0755 "${STAGE_DIR}/DEBIAN/postinst"

DEB_OUT="${DIST_DIR}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "${STAGE_DIR}" "${DEB_OUT}"
echo "Built Debian package: ${DEB_OUT}"
