"""Offline tests for GitHub Releases version discovery and safe UI update actions."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from omni_mouse import updater


def mock_release(version="1.2.7", asset_url=None):
    name = f"omni-mouse-studio_{version}_all.deb"
    url = asset_url if asset_url is not None else (
        f"https://github.com/lbg2002/omni-mouse-studio/releases/download/v{version}/{name}"
    )
    return {
        "tag_name": f"v{version}",
        "prerelease": False, "draft": False,
        "assets": [{"name": name, "browser_download_url": url}],
        "body": "Bug fixes and improvements",
    }


class TestGitHubUpdateDiscovery(unittest.TestCase):
    def test_versions_compare_numerically_not_lexically(self):
        self.assertGreater(updater.parse_version("v1.2.10"), updater.parse_version("1.2.9"))
        for invalid in ("", "main", "v1.2", "v1.2.3-rc1", "../v9.0.0", "1.2.3.4"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                updater.parse_version(invalid)

    def test_version_file_used_in_source_or_deb(self):
        self.assertEqual(updater.current_version(), "1.2.6")

    def test_new_release_verified_and_downloadable(self):
        payload = json.dumps(mock_release()).encode()
        with mock.patch.object(updater, "current_version", return_value="1.2.6"), \
             mock.patch.object(updater.urllib.request, "urlopen", return_value=io.BytesIO(payload)) as opener:
            out = updater.get_latest_release()
        self.assertTrue(out["ok"])
        self.assertTrue(out["update_available"])
        self.assertTrue(out["has_deb"])
        self.assertEqual(out["latest_version"], "1.2.7")
        self.assertTrue(out["deb_url"].endswith("omni-mouse-studio_1.2.7_all.deb"))
        self.assertEqual(opener.call_args.kwargs["timeout"], 8)

    def test_existing_version_or_older_not_offered(self):
        with mock.patch.object(updater, "current_version", return_value="1.2.9"), \
             mock.patch.object(updater.urllib.request, "urlopen",
                               return_value=io.BytesIO(json.dumps(mock_release("1.2.7")).encode())):
            out = updater.get_latest_release()
        self.assertTrue(out["ok"])
        self.assertFalse(out["update_available"])

    def test_untrusted_asset_url_cannot_be_offered(self):
        unsafe = mock_release(asset_url="https://example.com/untrusted.deb")
        with mock.patch.object(updater, "current_version", return_value="1.2.6"), \
             mock.patch.object(updater.urllib.request, "urlopen",
                               return_value=io.BytesIO(json.dumps(unsafe).encode())):
            out = updater.get_latest_release()
        self.assertTrue(out["ok"])
        self.assertFalse(out["has_deb"])
        self.assertEqual(out["deb_url"], "")

    def test_missing_release_is_not_misreported_as_latest(self):
        error = urllib.error.HTTPError(updater.RELEASE_API, 404, "Not found", None, None)
        with mock.patch.object(updater.urllib.request, "urlopen", side_effect=error):
            out = updater.get_latest_release()
        self.assertFalse(out["ok"])
        self.assertFalse(out["update_available"])
        self.assertIn("尚未发布", out["error"])

    def test_invalid_metadata_fails_closed(self):
        invalid = mock_release(version="1.2.7")
        invalid["tag_name"] = "v1.2.7/../../"
        with mock.patch.object(updater.urllib.request, "urlopen",
                               return_value=io.BytesIO(json.dumps(invalid).encode())):
            out = updater.get_latest_release()
        self.assertFalse(out["ok"])
        self.assertEqual(out["deb_url"], "")


class TestUpdateHTTPRoutes(unittest.TestCase):
    def setUp(self):
        import http.client
        from omni_mouse.ui.server import start_studio_server
        self.http_client = http.client
        self.server, _ = start_studio_server(SimpleNamespace(token="update-test"))
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def request(self, method, path, data=b"", headers=None):
        conn = self.http_client.HTTPConnection(self.host, self.port, timeout=4)
        headers = {"X-Studio-Token": "update-test", **(headers or {})}
        conn.request(method, path, body=data, headers=headers)
        res = conn.getresponse()
        value = json.loads(res.read())
        status = res.status
        conn.close()
        return status, value

    def test_local_version_endpoint_does_not_call_github(self):
        with mock.patch("omni_mouse.ui.server.get_latest_release", side_effect=AssertionError("unexpected network")):
            status, payload = self.request("GET", "/api/update/info")
        self.assertEqual(status, 200)
        self.assertEqual(payload["current_version"], "1.2.6")

    def test_check_endpoint_delegates_to_release_checker(self):
        release = {"ok": True, "latest_version": "1.2.7"}
        with mock.patch("omni_mouse.ui.server.get_latest_release", return_value=release):
            status, payload = self.request("GET", "/api/update/check")
        self.assertEqual(status, 200)
        self.assertEqual(payload["latest_version"], "1.2.7")

    def test_open_rejects_arbitrary_target_and_never_spawns_command(self):
        with mock.patch("omni_mouse.ui.server.subprocess.Popen") as popen:
            status, value = self.request("POST", "/api/update/open",
                json.dumps({"target": "https://attacker.invalid/evil.deb"}).encode())
        self.assertEqual(status, 400)
        self.assertFalse(value["ok"])
        popen.assert_not_called()

    def test_open_deb_requires_newer_verified_release(self):
        release = {"ok": True, "update_available": False, "has_deb": True, "error": "", "deb_url": "unused"}
        with mock.patch("omni_mouse.ui.server.get_latest_release", return_value=release), \
             mock.patch("omni_mouse.ui.server.subprocess.Popen") as popen:
            status, value = self.request("POST", "/api/update/open",
                json.dumps({"target": "deb"}).encode())
        self.assertEqual(status, 404)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
