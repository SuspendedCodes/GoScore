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

    def test_both_sports_use_the_layout_engine_and_editor(self):
        for src, sport in (('web/js/overlay.js', 'cricket'), ('web/js/fb/overlay.js', 'football')):
            text = self.read(src)
            self.assertIn(f"createEngine({{ stage, sport: '{sport}' }})", text)
            self.assertIn("startEditor(", text)
            self.assertIn("/demo'", text)
        self.assertTrue((ROOT / 'web/js/layout-editor.js').is_file())
        self.assertTrue((ROOT / 'web/js/layout-engine.js').is_file())

    def test_cricket_logo_node_is_reused(self):
        source = self.read('web/js/overlay.js')
        self.assertIn('const logoNodes = new Map()', source)
        self.assertIn('logoNode(c.batting.logo)', source)

    def test_panels_no_longer_scroll_or_shrink_inside_the_canvas(self):
        for css in ('web/css/overlay.css', 'web/css/overlay_fb.css'):
            self.assertNotIn('max-width:calc(100% - 32px)', self.read(css))
            self.assertNotIn('gs-layout-edit', self.read(css))

    def test_no_placeholder_words_where_icons_belong(self):
        for src in ('web/js/fb/overlay.js', 'web/js/fb/score.js'):
            text = self.read(src)
            self.assertNotIn("'Football'", text)
            self.assertNotIn("'Scored' : 'Missed'", text)

    def test_optional_blocks_are_not_printed_as_null(self):
        self.assertIn("const fill = (el, ...kids)", self.read('web/js/overlay.js'))

if __name__ == '__main__':
    unittest.main()
