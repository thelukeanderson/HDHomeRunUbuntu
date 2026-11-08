"""Tests for hdhr-tv. Run with:  python3 -m unittest discover tests

They don't need a tuner or network access. The window test runs only when a
display and GTK 4 are available, and is skipped otherwise.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import re
import stat
import tempfile
import time
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
HOUR = 3600
T0 = 1_800_000_000 - 1_800_000_000 % hdhr.SLOT  # a half-hour boundary


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

    def test_title_includes_episode(self):
        self.assertEqual(hdhr.title_of(SHOWS[1]), "B: Pilot")
        self.assertEqual(hdhr.title_of(None), "")


class GuideDataTests(unittest.TestCase):
    def test_merge_drops_duplicates_and_sorts(self):
        a = {"4.1": [SHOWS[1], SHOWS[0]]}
        b = {"4.1": [SHOWS[1], {"StartTime": 300, "EndTime": 400, "Title": "C"}], "5.1": [SHOWS[0]]}
        merged = hdhr.merge_guides(a, b)
        self.assertEqual([s["Title"] for s in merged["4.1"]], ["A", "B", "C"])
        self.assertEqual(merged["5.1"], [SHOWS[0]])

    def test_fetch_guide_asks_for_more_hours_where_the_first_request_ends(self):
        urls = []

        def fetch(url, timeout=8):
            urls.append(url)
            if url.endswith("/discover.json"):
                return {"DeviceAuth": "abc"}
            if "Start=" in url:
                return [{"GuideNumber": "4.1", "Guide": [{"StartTime": 300, "EndTime": 400, "Title": "C"}]}]
            return [{"GuideNumber": "4.1", "Guide": SHOWS},
                    {"GuideNumber": "5.1", "Guide": [{"StartTime": 100, "EndTime": 250, "Title": "D"}]}]

        with mock.patch.object(hdhr, "fetch_json", fetch):
            guide = hdhr.fetch_guide("1.2.3.4")
        self.assertTrue(urls[-1].endswith("DeviceAuth=abc&Start=250"))  # earliest last-show end
        self.assertEqual([s["Title"] for s in guide["4.1"]], ["A", "B", "C"])

    def test_fetch_guide_keeps_first_hours_if_the_second_request_fails(self):
        def fetch(url, timeout=8):
            if url.endswith("/discover.json"):
                return {"DeviceAuth": "abc"}
            if "Start=" in url:
                raise OSError("timed out")
            return [{"GuideNumber": "4.1", "Guide": SHOWS}]

        with mock.patch.object(hdhr, "fetch_json", fetch):
            self.assertEqual(hdhr.fetch_guide("1.2.3.4"), {"4.1": SHOWS})

    def test_fetch_guide_without_internet_is_empty(self):
        with mock.patch.object(hdhr, "fetch_json", side_effect=OSError("offline")):
            self.assertEqual(hdhr.fetch_guide("1.2.3.4"), {})


class LayoutTests(unittest.TestCase):
    def test_window_starts_at_the_current_half_hour(self):
        t0, _ = hdhr.guide_window({}, T0 + 17 * 60)
        self.assertEqual(t0, T0)

    def test_window_runs_to_the_last_listing_rounded_up(self):
        guide = {"4.1": [{"StartTime": T0, "EndTime": T0 + 5 * HOUR + 60, "Title": "A"}]}
        self.assertEqual(hdhr.guide_window(guide, T0), (T0, T0 + 5 * HOUR + hdhr.SLOT))

    def test_window_has_a_minimum_and_maximum_length(self):
        self.assertEqual(hdhr.guide_window({}, T0), (T0, T0 + hdhr.MIN_HOURS * HOUR))
        huge = {"4.1": [{"StartTime": T0, "EndTime": T0 + 48 * HOUR, "Title": "A"}]}
        self.assertEqual(hdhr.guide_window(huge, T0), (T0, T0 + hdhr.MAX_HOURS * HOUR))

    def test_time_slots_every_half_hour(self):
        self.assertEqual(hdhr.time_slots(T0, T0 + HOUR), [T0, T0 + hdhr.SLOT])

    def test_cell_width_is_proportional_to_length(self):
        show = {"StartTime": T0 + HOUR, "EndTime": T0 + 2 * HOUR}
        self.assertEqual(hdhr.cell_span(show, T0, T0 + 3 * HOUR), (60 * hdhr.PX_PER_MIN, 60 * hdhr.PX_PER_MIN))

    def test_cells_are_clipped_to_the_window(self):
        started_earlier = {"StartTime": T0 - HOUR, "EndTime": T0 + 30 * 60}
        self.assertEqual(hdhr.cell_span(started_earlier, T0, T0 + HOUR), (0, 30 * hdhr.PX_PER_MIN))
        runs_past_end = {"StartTime": T0 + 30 * 60, "EndTime": T0 + 5 * HOUR}
        self.assertEqual(hdhr.cell_span(runs_past_end, T0, T0 + HOUR), (120, 120))

    def test_shows_outside_the_window_are_dropped(self):
        self.assertIsNone(hdhr.cell_span({"StartTime": T0 - HOUR, "EndTime": T0}, T0, T0 + HOUR))
        self.assertIsNone(hdhr.cell_span({"StartTime": T0 + HOUR, "EndTime": T0 + 2 * HOUR}, T0, T0 + HOUR))


class SearchTests(unittest.TestCase):
    CH = {"GuideNumber": "11.1", "GuideName": "KARE-HD"}

    def test_empty_search_matches_everything(self):
        self.assertTrue(hdhr.channel_matches(self.CH, [], "  "))

    def test_matches_channel_number_from_the_start(self):
        self.assertTrue(hdhr.channel_matches(self.CH, [], "11"))
        self.assertFalse(hdhr.channel_matches(self.CH, [], "1.1"))

    def test_matches_channel_name_ignoring_case(self):
        self.assertTrue(hdhr.channel_matches(self.CH, [], "kare"))

    def test_matches_any_show_title_or_episode(self):
        self.assertTrue(hdhr.channel_matches(self.CH, SHOWS, "pilot"))
        self.assertFalse(hdhr.channel_matches(self.CH, SHOWS, "jeopardy"))


class SetupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        # Pretend VLC, apt-get and GTK are installed unless a test says otherwise.
        for target, value in ((hdhr.shutil, "which"), (hdhr, "has_gtk")):
            patcher = mock.patch.object(target, value, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

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

    def test_missing_packages(self):
        self.assertEqual(hdhr.missing_packages(), [])
        with mock.patch.object(hdhr.shutil, "which", return_value=None):
            self.assertEqual(hdhr.missing_packages(), ["vlc"])
        with mock.patch.object(hdhr, "has_gtk", return_value=False):
            self.assertEqual(hdhr.missing_packages(), hdhr.GTK_PACKAGES)

    def test_installs_only_missing_packages(self):
        with mock.patch.object(hdhr, "has_gtk", return_value=False), \
             mock.patch.object(hdhr, "install_packages") as install, \
             mock.patch.object(hdhr, "fetch_json", fake_network()):
            run_quietly(hdhr.setup, self.home)
        install.assert_called_once_with(hdhr.GTK_PACKAGES)

    def test_failed_install_stops_setup(self):
        err = hdhr.subprocess.CalledProcessError(100, "apt-get")
        with mock.patch.object(hdhr, "has_gtk", return_value=False), \
             mock.patch.object(hdhr, "install_packages", side_effect=err):
            rc, out = run_quietly(hdhr.setup, self.home)
        self.assertEqual(rc, 1)
        self.assertIn("Install failed", out)
        self.assertFalse((self.home / ".local/bin/hdhr-tv").exists())

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


class CellStateTests(unittest.TestCase):
    SHOW = {"StartTime": 100, "EndTime": 200}

    def test_states(self):
        self.assertIsNone(hdhr.cell_state(self.SHOW, 99))           # upcoming
        self.assertEqual(hdhr.cell_state(self.SHOW, 100), "on-now")
        self.assertEqual(hdhr.cell_state(self.SHOW, 199), "on-now")
        self.assertEqual(hdhr.cell_state(self.SHOW, 200), "past")
        self.assertIsNone(hdhr.cell_state(None, 150))               # "No guide listings" block


class RaspberryPiTests(unittest.TestCase):
    def model_file(self, content):
        f = tempfile.NamedTemporaryFile("wb", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_detects_a_pi(self):
        # The real file ends in a NUL byte.
        self.assertTrue(hdhr.is_raspberry_pi(self.model_file(b"Raspberry Pi 5 Model B Rev 1.0\x00")))

    def test_other_computers_are_not_a_pi(self):
        self.assertFalse(hdhr.is_raspberry_pi(self.model_file(b"Pine64 RockPro64\x00")))
        self.assertFalse(hdhr.is_raspberry_pi("/nonexistent/model"))  # most PCs have no such file

    def test_non_pi_vlc_command_is_unchanged(self):
        self.assertEqual(hdhr.vlc_command("http://t/auto/v4.1", "4.1 WCCO"),
                         ["vlc", "--one-instance", "--no-playlist-enqueue",
                          "http://t/auto/v4.1", ":meta-title=4.1 WCCO"])

    def test_pi_vlc_command_adds_lighter_settings(self):
        cmd = hdhr.vlc_command("http://t/auto/v4.1", "4.1 WCCO", pi=True)
        url = cmd.index("http://t/auto/v4.1")
        self.assertEqual(cmd[:3], ["vlc", "--one-instance", "--no-playlist-enqueue"])
        self.assertIn("--deinterlace-mode=bob", cmd[:url])  # player options go before the URL
        self.assertNotIn("--deinterlace=1", cmd)             # forcing it on broke VLC's filter chain
        self.assertIn(":network-caching=2000", cmd[url:])   # per-channel options go after it

    def test_play_uses_pi_settings_only_on_a_pi(self):
        for pi in (False, True):
            with mock.patch.object(hdhr, "is_raspberry_pi", return_value=pi), \
                 mock.patch.object(hdhr.subprocess, "Popen") as popen, \
                 mock.patch.object(hdhr, "LOG", Path(tempfile.gettempdir()) / "hdhr-tv-test.log"), \
                 mock.patch.object(hdhr, "log"):
                hdhr.play("u", "4.1 W")
            self.assertEqual(popen.call_args.args[0], hdhr.vlc_command("u", "4.1 W", pi))

    def test_describe_throttled(self):
        self.assertEqual(hdhr.describe_throttled("throttled=0x0\n"), [])
        self.assertEqual(hdhr.describe_throttled("throttled=0x50005"), [
            "under-voltage right now", "throttled right now",
            "under-voltage since boot", "throttled since boot"])
        self.assertIsNone(hdhr.describe_throttled("error"))

    def run_check_pi(self, output):
        with mock.patch.object(hdhr.shutil, "which", return_value="/usr/bin/vcgencmd"), \
             mock.patch.object(hdhr.subprocess, "run",
                               return_value=mock.Mock(stdout=output)):
            return run_quietly(hdhr.check_pi)[1]

    def test_check_pi_healthy(self):
        self.assertIn("no overheating or power problems", self.run_check_pi("throttled=0x0"))

    def test_check_pi_suggests_power_supply_and_cooling(self):
        out = self.run_check_pi("throttled=0x80001")
        self.assertIn("27W", out)
        self.assertIn("Active Cooler", out)

    def test_check_pi_without_vcgencmd(self):
        with mock.patch.object(hdhr.shutil, "which", return_value=None):
            self.assertIn("libraspberrypi-bin", run_quietly(hdhr.check_pi)[1])

    def test_setup_runs_the_pi_check_only_on_a_pi(self):
        with tempfile.TemporaryDirectory() as home:
            for pi in (False, True):
                with mock.patch.object(hdhr.shutil, "which", return_value=True), \
                     mock.patch.object(hdhr, "has_gtk", return_value=True), \
                     mock.patch.object(hdhr, "fetch_json", fake_network()), \
                     mock.patch.object(hdhr, "is_raspberry_pi", return_value=pi), \
                     mock.patch.object(hdhr, "check_pi") as check_pi:
                    run_quietly(hdhr.setup, home)
                self.assertEqual(check_pi.called, pi)


class WatchTests(unittest.TestCase):
    def test_refuses_to_start_until_set_up(self):
        with mock.patch.object(hdhr, "missing_packages", return_value=["vlc"]), \
             mock.patch.object(hdhr, "run_gui") as gui, \
             mock.patch.object(hdhr.shutil, "which", return_value=None), \
             contextlib.redirect_stderr(io.StringIO()) as err, \
             self.assertRaises(SystemExit):
            hdhr.watch()
        gui.assert_not_called()
        self.assertIn("--setup", err.getvalue())


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "no display")
@unittest.skipUnless(hdhr.has_gtk(), "GTK 4 / libadwaita not installed")
class WindowTests(unittest.TestCase):
    """Builds the real window from fake data, checks it, and closes it."""

    def open_window(self, lineup, guide, check):
        now = time.time()
        fetch = fake_network()

        def fake_fetch(url, timeout=8):
            return lineup if url.endswith("/lineup.json") else fetch(url, timeout)

        results = {}

        def ready(win):
            try:
                check(win, now)
                results["ok"] = True
            except Exception as e:  # report after the main loop exits
                results["error"] = e
            win.get_application().quit()

        with mock.patch.object(hdhr, "log"):
            hdhr.run_gui("1.2.3.4", on_ready=ready, unique=False,
                         fetch=fake_fetch, guide_fetch=lambda ip: guide)
        if "error" in results:
            raise results["error"]
        self.assertTrue(results.get("ok"), "window never finished loading")

    @staticmethod
    def x_of(widget):
        """Where a widget sits in its Gtk.Fixed, read from its layout transform."""
        transform = widget.get_parent().get_child_transform(widget)
        match = re.match(r"translate\(([-\d.]+)", transform.to_string()) if transform else None
        return float(match.group(1)) if match else 0.0

    @staticmethod
    def children(widget):
        child = widget.get_first_child()
        while child is not None:
            yield child
            child = child.get_next_sibling()

    def test_guide_shows_channels_shows_and_search(self):
        now = time.time()
        lineup = [
            {"GuideNumber": "4.1", "GuideName": "WCCO", "URL": "u1"},
            {"GuideNumber": "5.1", "GuideName": "KSTP", "URL": "u2"},
            {"GuideNumber": "9.1", "GuideName": "LOCKED", "URL": "u3", "DRM": 1},
        ]
        guide = {
            "4.1": [{"StartTime": now - 600, "EndTime": now + 1200, "Title": "News"},
                    {"StartTime": now + 1200, "EndTime": now + 4800, "Title": "Movie"}],
        }

        def check(win, now):
            from gi.repository import Gtk
            self.assertEqual(len(list(self.children(win.channels))), 2)  # DRM channel hidden
            cells = [c for c in self.children(win.cells) if isinstance(c, Gtk.Button)]
            self.assertEqual(len(cells), 3)  # News, Movie, and a "No guide listings" block for 5.1
            self.assertEqual(sum(c.has_css_class("on-now") for c in cells), 1)
            self.assertIn("2 channels", win.heading.get_subtitle())

            win.search.set_text("movie")
            win.render()  # search-changed is debounced; draw now
            self.assertEqual(len(list(self.children(win.channels))), 1)

            with mock.patch.object(hdhr, "play") as play:
                win.play(lineup[0])
            play.assert_called_once_with("u1", "4.1 WCCO")
            self.assertIn("watching 4.1 WCCO", win.heading.get_subtitle())

        self.open_window(lineup, guide, check)

    def test_minute_updates_restyle_without_rebuilding(self):
        now = time.time()
        lineup = [{"GuideNumber": "4.1", "GuideName": "WCCO", "URL": "u1"},
                  {"GuideNumber": "5.1", "GuideName": "KSTP", "URL": "u2"}]
        guide = {"4.1": [{"StartTime": now - 600, "EndTime": now + 1200, "Title": "News"},
                         {"StartTime": now + 1200, "EndTime": now + 4800, "Title": "Movie"}]}

        def check(win, now):
            from gi.repository import Gtk
            before = list(self.children(win.cells))
            news, movie = [b for b, _ in win.timed_cells]
            line = win.now_lines[0][1]
            x_before = self.x_of(line)
            self.assertGreater(x_before, 0)

            with mock.patch.object(hdhr.time, "time", return_value=now + 1500):  # 25 min later
                win.tick()
            self.assertEqual(list(self.children(win.cells)), before)  # same widgets, no rebuild
            self.assertTrue(news.has_css_class("past"))
            self.assertTrue(movie.has_css_class("on-now"))
            self.assertFalse(news.has_css_class("on-now"))
            self.assertAlmostEqual(self.x_of(line) - x_before, 25 * hdhr.PX_PER_MIN, delta=hdhr.PX_PER_MIN)

            channels_before = list(self.children(win.channels))
            with mock.patch.object(hdhr, "play"):
                win.play(lineup[1])
            self.assertEqual(list(self.children(win.channels)), channels_before)
            self.assertTrue(win.channel_buttons["5.1 KSTP"].has_css_class("watching"))
            self.assertFalse(win.channel_buttons["4.1 WCCO"].has_css_class("watching"))
            self.assertTrue(all(isinstance(b, Gtk.Button) for b, _ in win.timed_cells))

        self.open_window(lineup, guide, check)


if __name__ == "__main__":
    unittest.main()
