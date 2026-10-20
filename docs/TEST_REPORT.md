# Test report — overlay layout editor correction

Focused tests run in the Linux development environment:

- `node --check web/js/layout-editor.js` — passed
- `node --check web/js/overlay.js` — passed
- `node --check web/js/fb/overlay.js` — passed
- `python -m py_compile goscore/server.py` — passed
- `python -m unittest tests.test_api.Api.test_shared_overlay_layout_round_trip_and_validation tests.test_overlay_feature_smoke -v` — 8 tests passed, including shared layout API persistence and existing overlay smoke checks.

A full `python -m unittest discover -s tests -v` run was attempted. It passed several API and cricket engine tests but exceeded the execution time limit during the long-running fuzz test. Therefore the complete suite is **not certified as passing**. Browser/OBS visual verification on Windows remains required before calling the release stable.
