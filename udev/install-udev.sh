#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULE_SRC="${SCRIPT_DIR}/99-delux-m618xsd.rules"
RULE_DST="/etc/udev/rules.d/99-delux-m618xsd.rules"

install -m 0644 "${RULE_SRC}" "${RULE_DST}"
modprobe uinput || true
udevadm control --reload-rules
udevadm trigger --subsystem-match=hidraw
udevadm trigger --subsystem-match=input
udevadm trigger --subsystem-match=misc

# Also grant immediate ACL to the invoking desktop user so no replug is needed
TARGET_USER="${SUDO_USER:-}"
if [ -z "${TARGET_USER}" ] && [ -n "${PKEXEC_UID:-}" ]; then
    TARGET_USER="$(id -nu "${PKEXEC_UID}")"
fi

if [ -n "${TARGET_USER}" ]; then
    if [ -e /dev/uinput ]; then
        setfacl -m "u:${TARGET_USER}:rw" /dev/uinput || true
    fi
    for h in /sys/class/hidraw/hidraw*; do
        [ -e "${h}/device/uevent" ] || continue
        if grep -Eqi "00001D57|000030FA|000018F8" "${h}/device/uevent"; then
            dev="/dev/$(basename "${h}")"
            [ -e "${dev}" ] && setfacl -m "u:${TARGET_USER}:rw" "${dev}" || true
        fi
    done
    for ev in /sys/class/input/event*; do
        [ -e "${ev}/device/uevent" ] || continue
        if grep -Eqi "1D57|30FA|18F8|LXDDZ|INSTANT|INPHIC" "${ev}/device/uevent"; then
            dev="/dev/input/$(basename "${ev}")"
            [ -e "${dev}" ] && setfacl -m "u:${TARGET_USER}:rw" "${dev}" || true
        fi
    done
fi

echo "Multi-mouse (Delux M618XSD & Inphic W1) udev rules installed and applied successfully."
