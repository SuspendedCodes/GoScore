"""Overlay layout: sample matches (goscore/demo.py), layout validation and the layout API."""
import json, os, shutil, sys, tempfile, threading, unittest, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from goscore import demo, server, sports as S  # noqa: E402


class DemoMatches(unittest.TestCase):
    def test_every_sample_replays_without_a_single_rule_error(self):
        for sport, kinds in demo.KINDS.items():
            for kind in kinds:
                m = demo.build(sport, kind, 1_800_000_000_000)
                S.normalize_setup(m)
                st = S.derive(m)
                self.assertEqual(st["integrity"]["errors"], [], f"{sport}/{kind}")

    def test_cricket_samples_show_what_the_panels_need(self):
        now = 1_800_000_000_000
        chase = S.derive(self._norm(demo.build("cricket", "limited", now)))
        self.assertIsNotNone(chase["current"]["target"])              # chase panel + target text
        self.assertGreater(chase["current"]["need"], 0)
        self.assertIsNone(chase["play"])                                # not a multi-day match
        test = S.derive(self._norm(demo.build("cricket", "test", now)))
        self.assertIsNotNone(test["play"])                              # multi-day summary needs this
        fin = S.derive(self._norm(demo.build("cricket", "final", now)))
        self.assertTrue(fin["result"]["final"])

    def test_football_samples(self):
        now = 1_800_000_000_000
        live = S.derive(self._norm(demo.build("football", "live", now)))
        self.assertEqual(live["phase"], "p2")
        self.assertEqual((live["score"]["A"], live["score"]["B"]), (2, 1))
        self.assertTrue(live["clock"]["running"])
        so = S.derive(self._norm(demo.build("football", "shootout", now)))
        self.assertTrue(so["shootout"]["started"])
        self.assertFalse(so["shootout"]["decided"])

    @staticmethod
    def _norm(m):
        S.normalize_setup(m)
        return m


class LayoutValidation(unittest.TestCase):
    def test_unknown_ids_and_bad_numbers_are_dropped(self):
        out = server.clean_layout("cricket", {"bug": {"x": 10, "y": 20, "w": 300, "h": 100}, "nope": {"x": 1, "y": 1, "w": 100, "h": 100},
                                              "p-fow": {"x": "a", "y": 0, "w": 100, "h": 100}})
        self.assertEqual(list(out), ["bug"])

    def test_boxes_are_kept_on_the_canvas_and_above_the_minimum(self):
        b = server.clean_layout("football", {"bug": {"x": 1900, "y": -50, "w": 400, "h": 5}})["bug"]
        self.assertEqual((b["x"], b["y"], b["w"], b["h"]), (1520.0, 0.0, 400.0, 24.0))

    def test_stacking_order_is_kept_and_old_lower_third_id_is_migrated(self):
        out = server.clean_layout("cricket", {"lower": {"x": 5, "y": 5, "w": 500, "h": 200, "z": 7}})
        self.assertEqual(out["l-card"]["z"], 7)

    def test_ids_match_the_real_overlay_elements(self):
        for pid in ("bug", "popup", "l-card", "p-scorecard", "p-testsum", "p-overs"):
            self.assertIn(pid, server.CRICKET_LAYOUT_IDS)
        self.assertNotIn("pn-table", server.FOOTBALL_LAYOUT_IDS)         # the 1.0.0 editor listed a box that never existed
        panel_keys = set(server.FB.__dict__.get("FOOTBALL_PANELS", [])) or set(server.FOOTBALL_PANELS)
        for k in panel_keys - {"shootout"}:
            self.assertIn("pn-" + k, server.FOOTBALL_LAYOUT_IDS)


class LayoutApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.srv, cls.app = server.make_server("127.0.0.1", 0, os.path.join(cls.tmp, "d"), os.path.join(cls.tmp, "o"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.app.stop.set(); cls.srv.shutdown(); cls.srv.server_close(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def test_round_trip_changes_rev_and_sports_are_separate(self):
        r0 = self.call("GET", "/api/layout/football")
        self.call("PUT", "/api/layout/football", {"layout": {"pn-lineups": {"x": 100, "y": 50, "w": 900, "h": 700, "z": 2}}})
        r1 = self.call("GET", "/api/layout/football")
        self.assertNotEqual(r0["rev"], r1["rev"])
        self.assertEqual(r1["layout"]["pn-lineups"]["z"], 2)
        self.assertNotIn("pn-lineups", self.call("GET", "/api/layout/cricket")["layout"])

    def test_demo_endpoint_serves_published_shaped_payloads(self):
        d = self.call("GET", "/api/layout/cricket/demo")
        self.assertEqual(set(d["sets"]), {"limited", "test", "final"})
        p = d["sets"]["limited"]
        self.assertTrue(p["graphics"]["panels"]["scorecard"] and p["graphics"]["panels"]["target"])
        self.assertNotIn("balls", p["state"]["innings"][0])               # same light() payload the overlay normally gets
        self.assertIn("server_time", p["state"])
        f = self.call("GET", "/api/layout/football/demo")
        self.assertEqual(set(f["sets"]), {"live", "shootout"})
        self.assertTrue(f["sets"]["live"]["graphics"]["panels"]["stats_classic"])
        self.assertIn("bug", d["ids"])


if __name__ == "__main__":
    unittest.main()
