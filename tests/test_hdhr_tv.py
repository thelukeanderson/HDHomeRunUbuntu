"""Tests for hdhr-tv. Run with:  python3 -m unittest discover tests

They don't need a tuner, a network connection, or a display.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "hdhr-tv"
_loader = importlib.machinery.SourceFileLoader("hdhr_tv", str(SCRIPT))
_spec = importlib.util.spec_from_loader("hdhr_tv", _loader)
hdhr = importlib.util.module_from_spec(_spec)
_loader.exec_module(hdhr)

SHOWS = [
    {"StartTime": 100, "EndTime": 200, "Title": "A"},
    {"StartTime": 200, "EndTime": 300, "Title": "B", "EpisodeTitle": "Pilot"},
]


def fake_network(tuner_ip="192.168.0.215", reachable=True, devices=None):
    """Stand-in for fetch_json: the SiliconDust lookup plus the tuner's own pages."""
    def fetch(url, timeout=8):
        if "hdhomerun.com/discover" in url:
            return [{"LocalIP": tuner_ip}] if devices is None else devices
        if not reachable:
            raise OSError("timed out")
        if url.endswith("/discover.json"):
            return {"FriendlyName": "HDHomeRun FLEX DUO", "DeviceAuth": "x"}
        if url.endswith("/lineup.json"):
            return [{"GuideNumber": "4.1", "GuideName": "W", "URL": "u"}]
        raise AssertionError(f"unexpected url {url}")
    return fetch


def run_quietly(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args)
    return result, out.getvalue()


class ShowAtTests(unittest.TestCase):
    def test_during_a_show_returns_it_and_the_next(self):
        self.assertEqual(hdhr.show_at(SHOWS, 150), (SHOWS[0], SHOWS[1]))

    def test_at_a_boundary_the_new_show_is_current(self):
        self.assertEqual(hdhr.show_at(SHOWS, 200), (SHOWS[1], None))

    def test_before_the_guide_starts(self):
        self.assertEqual(hdhr.show_at(SHOWS, 50), (None, SHOWS[0]))

    def test_after_the_guide_ends(self):
        self.assertEqual(hdhr.show_at(SHOWS, 999), (None, None))

    def test_no_guide(self):
        self.assertEqual(hdhr.show_at([], 150), (None, None))


class RowTests(unittest.TestCase):
    def test_title_includes_episode(self):
        self.assertEqual(hdhr.title_of(SHOWS[1]), "B: Pilot")
        self.assertEqual(hdhr.title_of(None), "")

    def test_rows_skip_encrypted_channels_and_blank_missing_guide(self):
        lineup = [
            {"GuideNumber": "4.1", "GuideName": "W", "URL": "u"},
            {"GuideNumber": "9.1", "GuideName": "X", "URL": "v", "DRM": 1},
            {"GuideNumber": "5.1", "GuideName": "K", "URL": "w"},
        ]
        rows = hdhr.build_rows(lineup, {"4.1": SHOWS}, 150)
        self.assertEqual([r[0] for r in rows], ["4.1", "5.1"])
        self.assertEqual(rows[0][2:], ["A", hdhr.clock(200), "B: Pilot"])
        self.assertEqual(rows[1][2:], ["", "", ""])


class MenuChoiceTests(unittest.TestCase):
    def test_picked_channel(self):
        self.assertEqual(hdhr.menu_choice(0, "4.1|WCCO\n", ""), "4.1")

    def test_ok_with_nothing_selected_is_quit(self):
        self.assertIsNone(hdhr.menu_choice(0, "", ""))

    def test_quit_button(self):
        self.assertIsNone(hdhr.menu_choice(1, "", ""))

    def test_menu_failure_is_an_error_not_a_silent_quit(self):
        for rc in (255, -1, 5):
            with self.assertRaises(hdhr.MenuError) as cm:
                hdhr.menu_choice(rc, "", "cannot open display")
            self.assertIn("cannot open display", str(cm.exception))


class SetupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        # Pretend vlc, zenity and apt-get are installed.
        self.which = mock.patch.object(hdhr.shutil, "which", return_value="/usr/bin/x")
        self.which.start()
        self.addCleanup(self.which.stop)

    def test_installs_script_and_menu_entry(self):
        with mock.patch.object(hdhr, "fetch_json", fake_network()):
            rc, out = run_quietly(hdhr.setup, self.home)
        exe = self.home / ".local/bin/hdhr-tv"
        entry = self.home / ".local/share/applications/hdhr-tv.desktop"
        self.assertEqual(rc, 0, out)
        self.assertEqual(exe.read_bytes(), SCRIPT.read_bytes())
        self.assertTrue(exe.stat().st_mode & stat.S_IXUSR)
        self.assertIn(f"Exec={exe}\n", entry.read_text())
        self.assertIn("1 channels", out)

    def test_running_twice_is_safe(self):
        with mock.patch.object(hdhr, "fetch_json", fake_network()):
            run_quietly(hdhr.setup, self.home)
            rc, _ = run_quietly(hdhr.setup, self.home)
        self.assertEqual(rc, 0)

    def test_installs_only_missing_programs(self):
        self.which.stop()
        with mock.patch.object(hdhr.shutil, "which", side_effect=lambda c: None if c == "zenity" else "/x"), \
             mock.patch.object(hdhr, "install_packages") as install, \
             mock.patch.object(hdhr, "fetch_json", fake_network()):
            run_quietly(hdhr.setup, self.home)
        install.assert_called_once_with(["zenity"])
        self.which.start()

    def test_failed_install_stops_setup(self):
        self.which.stop()
        err = hdhr.subprocess.CalledProcessError(100, "apt-get")
        with mock.patch.object(hdhr.shutil, "which", side_effect=lambda c: None if c == "vlc" else "/x"), \
             mock.patch.object(hdhr, "install_packages", side_effect=err):
            rc, out = run_quietly(hdhr.setup, self.home)
        self.assertEqual(rc, 1)
        self.assertIn("Install failed", out)
        self.assertFalse((self.home / ".local/bin/hdhr-tv").exists())
        self.which.start()

    def test_tuner_on_a_different_network_is_explained(self):
        with mock.patch.object(hdhr, "fetch_json", fake_network("192.168.0.215", reachable=False)), \
             mock.patch.object(hdhr, "local_ips", return_value=["192.168.1.131"]):
            rc, out = run_quietly(hdhr.setup, self.home)
        self.assertEqual(rc, 2)
        self.assertIn("different network", out)

    def test_no_tuner_found(self):
        with mock.patch.object(hdhr, "fetch_json", fake_network(devices=[])):
            rc, out = run_quietly(hdhr.setup, self.home)
        self.assertEqual(rc, 2)
        self.assertIn("Couldn't look up the tuner", out)

    def test_subnet_check(self):
        self.assertTrue(hdhr.same_subnet24("192.168.0.215", "192.168.0.245"))
        self.assertFalse(hdhr.same_subnet24("192.168.0.215", "192.168.1.131"))


if __name__ == "__main__":
    unittest.main()
