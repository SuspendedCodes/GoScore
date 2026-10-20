"""API / persistence / broadcast-output tests (standard library only)."""
import base64, json, os, shutil, sys, tempfile, threading, time, unittest, urllib.request, urllib.error
import xml.dom.minidom as minidom

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from goscore.server import make_server  # noqa: E402


def players(prefix, names):
    return [{"id": f"{prefix}{i+1}", "name": n} for i, n in enumerate(names)]

A = ["Virat Kohli", "Rohit Sharma", "K L Rahul", "Rishabh Pant", "Hardik Pandya", "Ravindra Jadeja",
     "R Ashwin", "Jasprit Bumrah", "Mohammed Shami", "Kuldeep Yadav", "Axar Patel"]
B = ["Steve Smith", "David Warner", "Marnus Labuschagne", "Travis Head", "Glenn Maxwell", "Mitchell Marsh",
     "Alex Carey", "Pat Cummins", "Mitchell Starc", "Adam Zampa", "Josh Hazlewood"]


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.srv, cls.app = make_server("127.0.0.1", 0, os.path.join(cls.tmp, "data"), os.path.join(cls.tmp, "out"))
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.app.stop.set(); cls.srv.shutdown(); cls.srv.server_close(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, expect=200, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                payload = r.read()
                code = r.status
        except urllib.error.HTTPError as e:
            payload, code = e.read(), e.code
        self.assertEqual(code, expect, payload[:300])
        return payload if raw else json.loads(payload)

    def new_match(self, overs=2):
        r = self.call("POST", "/api/matches", {"title": "India v Australia", "format": {"preset": "custom", "overs": overs},
                                                "teams": {"A": {"name": "India", "short": "IND", "players": players("A", A)},
                                                          "B": {"name": "Australia", "short": "AUS", "players": players("B", B)}},
                                                "toss": {"winner": "A", "decision": "bat"}}, 201)
        return r["id"]

    def ev(self, mid, **kw):
        kw.setdefault("cid", os.urandom(6).hex())
        return self.call("POST", f"/api/matches/{mid}/events", kw)

    def test_full_flow_outputs_xml_text_files_idempotency_undo(self):
        mid = self.new_match()
        self.call("POST", f"/api/matches/{mid}/go-live", {})
        self.ev(mid, type="innings_start", innings=0, batting="A", striker="A1", non_striker="A2", bowler="B8")
        c = os.urandom(4).hex()
        self.ev(mid, type="ball", innings=0, bat_runs=1, cid=c)
        dup = self.ev(mid, type="ball", innings=0, bat_runs=1, cid=c)       # double click / retry
        self.assertTrue(dup.get("duplicate"))
        st = self.call("GET", f"/api/matches/{mid}/state")["state"]
        self.assertEqual(st["current"]["score"], "1/0")
        self.assertEqual(st["current"]["striker"]["name"], "Rohit Sharma")
        # illegal ball is refused with an explanation, nothing is stored
        r = self.call("POST", f"/api/matches/{mid}/events", {"type": "ball", "innings": 0, "delivery": "noball",
                      "wicket": {"kind": "bowled"}}, 422)
        self.assertEqual(r["error"]["code"], "illegal_dismissal")
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/state")["state"]["current"]["score"], "1/0")
        # XML must be well-formed even with spaces / initials / apostrophes in names
        xml = self.call("GET", f"/feed/{mid}.xml", raw=True)
        doc = minidom.parseString(xml)
        self.assertTrue(doc.getElementsByTagName("striker"))
        self.assertIn(b"Rohit Sharma", xml)
        # feeds
        j = self.call("GET", "/feed/live.json")
        self.assertEqual(j["state"]["current"]["score"], "1/0")
        self.assertEqual(self.call("GET", "/feed/live/text/score.txt", raw=True), b"1/0")
        # files on disk
        live = os.path.join(self.tmp, "out", "live")
        for f in ("scoreboard.json", "scoreboard.xml", "text/score.txt", "text/striker.txt", "csv/batting.csv"):
            self.assertTrue(os.path.exists(os.path.join(live, f)), f)
        self.assertEqual(open(os.path.join(live, "text", "score.txt")).read(), "1/0")
        self.assertEqual(open(os.path.join(live, "text", "striker.txt")).read(), "R Sharma* 0 (0)")
        # undo / redo
        self.call("POST", f"/api/matches/{mid}/undo", {})
        self.assertEqual(open(os.path.join(live, "text", "score.txt")).read(), "0/0")
        self.call("POST", f"/api/matches/{mid}/redo", {})
        self.assertEqual(open(os.path.join(live, "text", "score.txt")).read(), "1/0")

    def test_uploaded_logo_and_team_reference_survive_refresh_and_server_restart(self):
        # The upload route verifies the image signature; a small PNG signature fixture is enough here.
        image = b"\x89PNG\r\n\x1a\n" + b"GoScore test image"
        payload = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
        uploaded = self.call("POST", "/api/logos", {"data": payload})
        logo_url = uploaded["url"]
        self.assertEqual(self.call("GET", logo_url, raw=True), image)

        mid = self.new_match()
        self.call("POST", f"/api/matches/{mid}/setup", {"patch": {"teams": {"A": {"logo": logo_url}}}})
        self.assertEqual(self.call("GET", f"/api/matches/{mid}")["teams"]["A"]["logo"], logo_url)

        # Reopen the same data directory to emulate restarting the app after a refresh.
        srv2, app2 = make_server("127.0.0.1", 0, os.path.join(self.tmp, "data"), os.path.join(self.tmp, "out2"))
        try:
            threading.Thread(target=srv2.serve_forever, daemon=True).start()
            base2 = f"http://127.0.0.1:{srv2.server_address[1]}"
            req = urllib.request.Request(base2 + logo_url)
            with urllib.request.urlopen(req, timeout=5) as response:
                self.assertEqual(response.read(), image)
            req = urllib.request.Request(base2 + f"/api/matches/{mid}")
            with urllib.request.urlopen(req, timeout=5) as response:
                saved = json.loads(response.read())
            self.assertEqual(saved["teams"]["A"]["logo"], logo_url)
        finally:
            app2.stop.set(); srv2.shutdown(); srv2.server_close()

    def test_edit_delete_insert_and_override(self):
        mid = self.new_match()
        self.ev(mid, type="innings_start", innings=0, batting="A", striker="A1", non_striker="A2", bowler="B8")
        e1 = self.ev(mid, type="ball", innings=0, bat_runs=1)["event"]["id"]
        self.ev(mid, type="ball", innings=0, bat_runs=0)
        self.call("PUT", f"/api/matches/{mid}/events/{e1}", {"patch": {"bat_runs": 4, "boundary": True}, "reason": "mis-tap"})
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/state")["state"]["current"]["score"], "4/0")
        self.call("POST", f"/api/matches/{mid}/insert", {"event": {"type": "ball", "innings": 0, "bat_runs": 2}, "after_id": e1})
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/state")["state"]["current"]["score"], "6/0")
        self.ev(mid, type="override", innings=0, set={"runs": 100, "wickets": 3}, reason="rebuilt from paper scorebook")
        s = self.call("GET", f"/api/matches/{mid}/state")["state"]
        self.assertEqual(s["current"]["score"], "100/3")
        self.assertTrue(s["innings"][0]["overridden"])
        self.call("DELETE", f"/api/matches/{mid}/events/{e1}")
        audit = self.call("GET", f"/api/matches/{mid}/audit")["audit"]
        self.assertIn("delete_event", [a["action"] for a in audit])
        self.assertIn("edit_event", [a["action"] for a in audit])

    def test_persistence_survives_restart_and_backups_exist(self):
        mid = self.new_match()
        self.ev(mid, type="innings_start", innings=0, batting="A", striker="A1", non_striker="A2", bowler="B8")
        self.ev(mid, type="ball", innings=0, bat_runs=6, boundary=True)
        from goscore.store import Store
        s2 = Store(os.path.join(self.tmp, "data"))
        self.assertEqual(len(s2.matches[mid]["events"]), 2)
        self.assertTrue(self.call("GET", f"/api/matches/{mid}/backups")["backups"])
        # restore an older version
        v = self.call("GET", f"/api/matches/{mid}/backups")["backups"][-1]["version"]
        self.call("POST", f"/api/matches/{mid}/restore", {"version": v})

    def test_target_display_and_over_window_settings_persist(self):
        mid = self.new_match()
        self.call("POST", f"/api/matches/{mid}/graphics", {"target_display": "both", "overs_start": 11})
        pub = self.call("GET", f"/api/matches/{mid}/published")
        self.assertEqual(pub["graphics"]["target_display"], "both")
        self.assertEqual(pub["graphics"]["overs_start"], 11)
        srv2, app2 = make_server("127.0.0.1", 0, os.path.join(self.tmp, "data"), os.path.join(self.tmp, "graphics-restart"))
        try:
            threading.Thread(target=srv2.serve_forever, daemon=True).start()
            req = urllib.request.Request(f"http://127.0.0.1:{srv2.server_address[1]}/api/matches/{mid}/published")
            with urllib.request.urlopen(req, timeout=5) as response:
                restarted = json.loads(response.read())
            self.assertEqual(restarted["graphics"]["target_display"], "both")
            self.assertEqual(restarted["graphics"]["overs_start"], 11)
        finally:
            app2.stop.set(); srv2.shutdown(); srv2.server_close()

    def test_hold_freezes_published_output_but_not_live_scoring(self):
        mid = self.new_match()
        self.ev(mid, type="innings_start", innings=0, batting="A", striker="A1", non_striker="A2", bowler="B8")
        self.ev(mid, type="ball", innings=0, bat_runs=1)
        self.call("POST", f"/api/matches/{mid}/graphics", {"hold": True})
        self.ev(mid, type="ball", innings=0, bat_runs=4, boundary=True)
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/published")["state"]["current"]["score"], "1/0")
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/state")["state"]["current"]["score"], "5/0")
        self.call("POST", f"/api/matches/{mid}/graphics", {"hold": False})
        self.assertEqual(self.call("GET", f"/api/matches/{mid}/published")["state"]["current"]["score"], "5/0")

    def test_publish_delay(self):
        mid = self.new_match()
        self.ev(mid, type="innings_start", innings=0, batting="A", striker="A1", non_striker="A2", bowler="B8")
        self.call("POST", "/api/settings", {"publish_delay": 1.0})
        try:
            self.ev(mid, type="ball", innings=0, bat_runs=2)
            self.assertEqual(self.call("GET", f"/api/matches/{mid}/published")["state"]["current"]["score"], "0/0")
            time.sleep(1.6)
            self.assertEqual(self.call("GET", f"/api/matches/{mid}/published")["state"]["current"]["score"], "2/0")
        finally:
            self.call("POST", "/api/settings", {"publish_delay": 0})

    def test_sse_stream_pushes_update(self):
        mid = self.new_match()
        self.ev(mid, type="innings_start", innings=0, batting="A", striker="A1", non_striker="A2", bowler="B8")
        got = []
        def reader():
            req = urllib.request.Request(self.base + f"/api/matches/{mid}/stream?ch=pub")
            with urllib.request.urlopen(req, timeout=8) as r:
                buf = b""
                t0 = time.time()
                while time.time() - t0 < 6:
                    line = r.readline()
                    if line.startswith(b"data:"):
                        got.append(json.loads(line[5:]))
                        if len(got) >= 2:
                            return
        th = threading.Thread(target=reader); th.start(); time.sleep(0.6)
        self.ev(mid, type="ball", innings=0, bat_runs=3)
        th.join(8)
        self.assertGreaterEqual(len(got), 2)
        self.assertEqual(got[-1]["state"]["current"]["score"], "3/0")

    def test_shared_overlay_layout_round_trip_and_validation(self):
        initial = self.call("GET", "/api/layout/cricket")
        self.assertEqual(initial["sport"], "cricket")
        saved = {"bug": {"x": 120, "y": 760, "w": 700, "h": 180}}
        result = self.call("PUT", "/api/layout/cricket", {"layout": saved})
        self.assertTrue(result["ok"])
        self.assertEqual(self.call("GET", "/api/layout/cricket")["layout"], saved)
        self.assertEqual(self.call("GET", "/api/layout/football")["layout"], {})

    def test_pin_protects_writes_only(self):
        srv, app = make_server("127.0.0.1", 0, os.path.join(self.tmp, "d2"), os.path.join(self.tmp, "o2"), pin="4242")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            self.assertEqual(urllib.request.urlopen(base + "/api/matches").status, 200)
            req = urllib.request.Request(base + "/api/matches", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen(req)
            self.assertEqual(c.exception.code, 401)
            req = urllib.request.Request(base + "/api/matches", data=b"{}", method="POST", headers={"Content-Type": "application/json", "X-Pin": "4242"})
            self.assertEqual(urllib.request.urlopen(req).status, 201)
        finally:
            app.stop.set(); srv.shutdown(); srv.server_close()

if __name__ == "__main__":
    unittest.main(verbosity=2)
