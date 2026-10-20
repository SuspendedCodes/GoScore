"""Static smoke checks for overlay feature wiring; these complement browser testing."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class OverlayFeatureSmokeTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding='utf-8')

    def test_football_panels_use_short_polling(self):
        source = self.read('web/js/fb/overlay.js')
        self.assertIn("stream: false, pollMs: 1500", source)

    def test_cricket_slideshow_has_separate_url_and_controls(self):
        control = self.read('web/js/control.js')
        overlay = self.read('web/js/overlay.js')
        self.assertIn('only=panels&slideshow=1', control)
        self.assertIn('function syncSlideshow', overlay)
        self.assertIn('slideshowOnly ? false', overlay)

    def test_both_sports_load_layout_editor(self):
        self.assertIn("sport: 'cricket'", self.read('web/js/overlay.js'))
        self.assertIn("sport: 'football'", self.read('web/js/fb/overlay.js'))
        self.assertTrue((ROOT / 'web/js/layout-editor.js').is_file())

    def test_cricket_logo_node_is_reused(self):
        source = self.read('web/js/overlay.js')
        self.assertIn('const logoNodes = new Map()', source)
        self.assertIn('logoNode(c.batting.logo)', source)

    def test_overlays_preserve_intrinsic_panel_dimensions_for_uniform_scaling(self):
        for name in ('web/css/overlay.css', 'web/css/overlay_fb.css'):
            css = self.read(name)
            self.assertNotIn('max-width:calc(100% - 32px)', css)
            self.assertNotIn('max-height:calc(100% - 32px)', css)
        editor = self.read('web/js/layout-editor.js')
        self.assertIn('Uniform scaling preserves the real graphic', editor)

if __name__ == '__main__':
    unittest.main()


class LayoutEditorRevisionTests(unittest.TestCase):
    def test_layout_editor_has_preview_menu_and_shared_save(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "web/js/layout-editor.js").read_text(encoding="utf-8")
        self.assertIn("gs-layout-sidebar", js)
        self.assertIn("gs-layout-list", js)
        self.assertIn("/api/layout/${sport}", js)
        self.assertIn("request('PUT',{layout})", js)
        self.assertIn("/overlay/live", js)

    def test_server_persists_layout_for_overlay_and_obs(self):
        root = Path(__file__).resolve().parents[1]
        server = (root / "goscore/server.py").read_text(encoding="utf-8")
        self.assertIn('seg[:2] == ["api", "layout"]', server)
        self.assertIn('"overlay_layouts.json"', server)
        self.assertIn('os.replace(tmp, layout_path)', server)
