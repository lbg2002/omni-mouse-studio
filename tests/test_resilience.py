"""Regression checks for background residency and device reconnects (no hardware required)."""
import errno
import os
import tempfile
import unittest
from unittest import mock

from omni_mouse.daemon.engine import SmartMouseDaemon
from omni_mouse.daemon import linux_input as li


class TestResidentRecovery(unittest.TestCase):
    def test_evdev_eof_triggers_reconnect(self):
        reader = li.PhysicalMouseReader("/dev/input/event999")
        reader.fd = 123
        with mock.patch.object(li.os, "read", return_value=b""):
            with self.assertRaises(OSError) as raised:
                reader.read_events()
        self.assertEqual(raised.exception.errno, errno.ENODEV)

    def test_partial_uinput_creation_is_rolled_back(self):
        pair = li.VirtualInputPair()
        with mock.patch.object(li, "_setup_uinput_device", side_effect=[88, OSError(errno.EACCES, "denied")]), \
             mock.patch.object(li.fcntl, "ioctl"), mock.patch.object(li.os, "close") as closer:
            with self.assertRaises(OSError):
                pair.open()
            closer.assert_called_once_with(88)
        self.assertIsNone(pair.mouse_fd)
        self.assertIsNone(pair.kbd_fd)

    def test_uinput_unavailable_keeps_daemon_retriable(self):
        daemon = SmartMouseDaemon()
        with mock.patch.object(daemon.virtual, "open", side_effect=OSError(errno.EACCES, "permission denied")), \
             mock.patch.object(daemon.virtual, "close") as closer:
            daemon._ensure_virtual_input(10.0)
            self.assertFalse(daemon._virtual_ready)
            self.assertEqual(daemon._virtual_retry_at, 15.0)
            daemon._ensure_virtual_input(12.0)
            self.assertEqual(closer.call_count, 1)
        with mock.patch.object(daemon.virtual, "open"):
            daemon._ensure_virtual_input(15.0)
        self.assertTrue(daemon._virtual_ready)
        self.assertEqual(daemon._virtual_error, "")

    def test_single_instance_socket_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = os.path.join(directory, "daemon.sock")
            one = SmartMouseDaemon(ipc_path=socket_path)
            two = SmartMouseDaemon(ipc_path=socket_path)
            try:
                self.assertTrue(one._acquire_instance_lock())
                self.assertFalse(two._acquire_instance_lock())
                one._release_instance_lock()
                self.assertTrue(two._acquire_instance_lock())
            finally:
                one._release_instance_lock()
                two._release_instance_lock()

    def test_uinput_write_error_releases_virtual_devices(self):
        daemon = SmartMouseDaemon()
        daemon._virtual_ready = True
        with mock.patch.object(daemon, "_process_batch", side_effect=OSError(errno.EIO, "broken uinput")), \
             mock.patch.object(daemon.virtual, "close") as closer:
            with self.assertRaises(OSError):
                daemon._process_batch_safe([])
            closer.assert_called_once()
        self.assertFalse(daemon._virtual_ready)


if __name__ == "__main__":
    unittest.main()
