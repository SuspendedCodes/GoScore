# Test report - GoScore 1.0.1

Run in the Linux development environment (Python 3.13, Chromium via Playwright):

- `python -m unittest discover -s tests` - **228 tests passed** (cricket and football engines, multi-day, API, the new layout tests, and the real-browser fit check).
- `tests/test_layout.py` - sample matches replay through the real engines with zero rule errors; layout validation; layout and sample-match API.
- `tests/test_layout_browser.py` - headless Chromium: for every graphic of both sports (17 cricket, 19 football) at six box shapes and sizes, the graphic and everything inside it stays inside its box (216 cases, 0 failures). Skipped automatically when Playwright is not installed.
- Interaction check in headless Chromium: select, drag, resize (aspect kept for scorebug), undo / redo, save, then the live overlay (with an intercepted published feed) applied the saved boxes to within 0.1 px.
- Contact sheets of every graphic at natural, wide and tall boxes were reviewed by eye.

Not tested: real OBS Browser Sources, Windows, and the packaged `.exe` (it can only be built on Windows with `BUILD_WINDOWS_EXE.bat`). Rehearse the layout in your own OBS before a live broadcast.
