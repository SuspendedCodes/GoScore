"""Real-browser check of the fit-to-box layout engine (needs `pip install playwright` + `playwright install chromium`; skipped otherwise).

For every graphic of both sports, at six box shapes/sizes, nothing may stick out of its box."""
import os, shutil, sys, tempfile, threading, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from goscore import server  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None

JS = """
async ({variants}) => {
  const E = window.__gsEditor, eng = E.engine; const res = [];
  const stage = document.getElementById('stage'); const sr0 = stage.getBoundingClientRect(); const k = sr0.width/1920;
  for (const id of E.order) {
    const el = document.getElementById(id); const nat = E.model.get(id);
    for (const v of variants) {
      const w = Math.max(60, Math.min(1920, nat.w*v[0])), h = Math.max(40, Math.min(1080, nat.h*v[1]));
      const x = Math.max(0, Math.min(1920-w, nat.x)), y = Math.max(0, Math.min(1080-h, nat.y));
      eng.setBox(id, {x,y,w,h}, true);
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      const er = el.getBoundingClientRect(); const bx = {l: sr0.left + x*k, t: sr0.top + y*k, r: sr0.left+(x+w)*k, b: sr0.top+(y+h)*k};
      const tol = 2;
      let bad = [];
      // element footprint must sit inside its box
      const target = el.firstElementChild && ['bug','tracker','popup'].includes(id) ? el.firstElementChild : el;
      const tr = target.getBoundingClientRect();
      if (tr.left < bx.l-tol || tr.top < bx.t-tol || tr.right > bx.r+tol || tr.bottom > bx.b+tol) bad.push('footprint');
      // every descendant must sit inside the footprint
      const walker = target.querySelectorAll('*'); let cnt=0;
      for (const d of walker) { const r = d.getBoundingClientRect(); if (r.width<1||r.height<1) continue; if (getComputedStyle(d).position==='absolute' && d.closest('svg')) continue;
        if (r.left < tr.left-tol || r.right > tr.right+tol || r.top < tr.top-tol || r.bottom > tr.bottom+tol) { cnt++; if (cnt<=2) bad.push('child '+d.tagName+'.'+d.className+' '+Math.round(r.right-tr.right)+','+Math.round(r.bottom-tr.bottom)); } }
      res.push({id, v:v.join('x'), scale: el.dataset.gsScale, bad});
    }
    eng.setBox(id, null, true);
  }
  return res;
}
"""
VARIANTS = [[1, 1], [1.5, 1.5], [0.6, 0.6], [1.6, 0.7], [0.7, 1.6], [0.45, 0.45]]


@unittest.skipIf(sync_playwright is None, "playwright is not installed")
class FitToBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.srv, cls.app = server.make_server("127.0.0.1", 0, os.path.join(cls.tmp, "d"), os.path.join(cls.tmp, "o"))
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.app.stop.set(); cls.srv.shutdown(); cls.srv.server_close(); shutil.rmtree(cls.tmp, ignore_errors=True)

    def check(self, sport):
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1600, "height": 900})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(f"{self.base}/overlay/live?edit=1&sport={sport}")
            pg.wait_for_function("window.__gsEditor && window.__gsEditor.order.length > 10", timeout=20000)
            rows = pg.evaluate(JS, {"variants": VARIANTS})
            b.close()
        self.assertEqual(errors, [])
        self.assertGreater(len(rows), 80)
        bad = [r for r in rows if r["bad"]]
        self.assertEqual(bad, [], bad[:3])

    def test_cricket(self):
        self.check("cricket")

    def test_football(self):
        self.check("football")


if __name__ == "__main__":
    unittest.main()
