from pathlib import Path
import unittest


class SuperOverUiRegression(unittest.TestCase):
    def test_completed_first_super_over_innings_offers_second_super_over(self):
        source = (Path(__file__).resolve().parents[1] / "web" / "js" / "score.js").read_text(encoding="utf-8")
        self.assertIn("const soCount = S.innings.filter(x => x.kind === 'super_over').length;", source)
        self.assertIn("const continuingSuperOver = c.kind === 'super_over' && soCount % 2 === 1;", source)
        self.assertIn("const so = !!S.result.super_over_needed || continuingSuperOver;", source)
        self.assertIn("onclick: () => startInningsModal(so)", source)

    def test_super_over_dialog_defaults_to_one_over(self):
        source = (Path(__file__).resolve().parents[1] / "web" / "js" / "score.js").read_text(encoding="utf-8")
        self.assertIn("value: superOver ? 1 : (S.format.overs || '')", source)


if __name__ == "__main__":
    unittest.main()
