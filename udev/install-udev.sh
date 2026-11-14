#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_SRC="${SCRIPT_DIR}/70-omni-mouse-studio.rules"
RULE_DST="/etc/udev/rules.d/70-omni-mouse-studio.rules"

# Remove legacy 99-* rules (99 ran after 73-seat-late.rules, causing uaccess ACL loss after overnight USB reset)
rm -f /etc/udev/rules.d/99-delux-m618xsd.rules \
      /etc/udev/rules.d/99-omni-mouse-studio.rules

install -m 0644 "${RULE_SRC}" "${RULE_DST}"
modprobe uinput || true

TARGET_USER="${SUDO_USER:-}"
if [ -z "${TARGET_USER}" ] && [ -n "${PKEXEC_UID:-}" ]; then
    TARGET_USER="$(id -nu "${PKEXEC_UID}")"
fi

# Ensure desktop user belongs to plugdev & input groups for permanent lock-screen / resume access
if [ -n "${TARGET_USER}" ]; then
    getent group plugdev >/dev/null 2>&1 && usermod -aG plugdev "${TARGET_USER}" || true
    getent group input >/dev/null 2>&1 && usermod -aG input "${TARGET_USER}" || true
fi

udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=usb || true
udevadm trigger --action=add --subsystem-match=hidraw || true
udevadm trigger --action=add --subsystem-match=input || true
udevadm trigger --action=add --subsystem-match=misc || true
udevadm settle --timeout=3 || true

# Disable USB autosuspend immediately on currently connected supported mice
for d in /sys/bus/usb/devices/*; do
    [ -f "${d}/idVendor" ] || continue
    vid="$(tr '[:upper:]' '[:lower:]' < "${d}/idVendor" 2>/dev/null || true)"
    if [ "${vid}" = "1d57" ] || [ "${vid}" = "30fa" ] || [ "${vid}" = "18f8" ]; then
        if [ -w "${d}/power/control" ]; then
            echo on > "${d}/power/control" || true
        fi
    fi
done

# Grant immediate group & ACL permissions on live nodes so no replug or logout is needed
if [ -e /dev/uinput ]; then
    chgrp plugdev /dev/uinput 2>/dev/null || true
    chmod 0660 /dev/uinput 2>/dev/null || true
    [ -n "${TARGET_USER}" ] && setfacl -m "u:${TARGET_USER}:rw" /dev/uinput || true
fi

for h in /sys/class/hidraw/hidraw*; do
    [ -e "${h}/device/uevent" ] || continue
    if grep -Eqi "00001D57|000030FA|000018F8" "${h}/device/uevent"; then
        dev="/dev/$(basename "${h}")"
        if [ -e "${dev}" ]; then
            chgrp plugdev "${dev}" 2>/dev/null || true
            chmod 0660 "${dev}" 2>/dev/null || true
            [ -n "${TARGET_USER}" ] && setfacl -m "u:${TARGET_USER}:rw" "${dev}" || true
        fi
    fi
done

for ev in /sys/class/input/event*; do
    [ -e "${ev}/device/uevent" ] || continue
    if grep -Eqi "1D57|30FA|18F8|LXDDZ|INSTANT|INPHIC" "${ev}/device/uevent"; then
        dev="/dev/input/$(basename "${ev}")"
        if [ -e "${dev}" ]; then
            chgrp plugdev "${dev}" 2>/dev/null || true
            chmod 0660 "${dev}" 2>/dev/null || true
            [ -n "${TARGET_USER}" ] && setfacl -m "u:${TARGET_USER}:rw" "${dev}" || true
        fi
    fi
done

echo "Omni Mouse Studio 70-udev rules installed and applied successfully."
