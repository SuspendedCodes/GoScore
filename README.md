# GoScore v1.0

Cricket scoring, football match management and OBS graphics in one local web app.

## Windows release

The repository includes the desktop launcher source and PyInstaller build specification. GitHub Actions runs the regression tests and builds a Windows `GoScore.exe` on a Windows runner. Download the `GoScore-Windows-x64` artifact from a successful workflow run, or download `GoScore.exe` from a GitHub Release created from a `v*` tag. The app opens a small GoScore window with Start, Open, and Stop controls, without an application console window. Match data and OBS output files are stored beside the executable in `data/` and `output/`.

To build locally on Windows, install Python 3.10 or newer and double-click `BUILD_WINDOWS_EXE.bat`. When it finishes, run `dist\GoScore.exe`.

For a quick source run instead, Python 3.8 or newer is sufficient and no third-party Python packages are needed: double-click `START_GOSCORE.bat`, then open `http://localhost:8000/`.

## Pages

- `/` — matches and feed links
- `/score/<match-id>` — scorer
- `/control/<match-id>` — production controls and OBS source links
- `/overlay/<match-id>` — complete overlay
- `/scorecard/<match-id>` — public scorecard
- `/setup/<match-id>` — teams and match setup

Use `live` instead of a match ID to follow the match marked as live. In OBS, add the individual URLs from Production as Browser Sources. Individual overlay sources use short polling requests rather than holding one long-lived connection each.

## Match data and images

Match data, backups, uploaded team logos and settings are saved in `data/`. OBS output files are written to `output/`. Keep these folders when updating the application and back them up before installing a new release.

## Cricket scoring notes

Byes and leg-byes are extras, not runs credited to the batter. The target panel can show runs required, wickets needed by the bowling side, or both. The over-by-over panel shows the last 10 overs by default; enter a starting over in Production to show that over and the next nine.

## Tests

Run the tests from the source folder with `python -m unittest discover -s tests`.

## Release note

This is GoScore v1.0.1, a hotfix for the overlay layout editor (see CHANGELOG.md). Rehearse with practice matches before using it for a live broadcast and report reproducible issues with the GoScore version and relevant logs.

## Overlay layout editor

Open the match overlay with `?edit=1` appended to its URL (for the live match, `/overlay/live?edit=1`), or use **Arrange overlay layout** on the Production page. It works like a slide editor:

- Every graphic is drawn exactly as it looks on air, using a sample match that is replayed by the real scoring engine (a T20 chase in progress, a Test match for the multi-day summary, a finished match for the result panels, a second-half football match and a penalty shoot-out). Nothing is placeholder text.
- Click a graphic (or its name in the list) to select it. Drag to move, drag a handle to resize. Shift-click or drag on empty space to select several; Alt-click selects what lies underneath.
- **Everything inside a box scales to fit that box.** Cards (scorecard, line-ups, statistics and so on) are stretched to the box and their content is scaled to the largest size that still fits; the scorebug, shoot-out tracker and pop-ups keep their proportions and are centred in the box. Nothing is cut off or spills outside, whatever data is on screen.
- Snapping to canvas edges, centre, safe areas and other graphics (hold Alt to switch off); Shift while resizing keeps the proportions; arrow keys nudge (Shift = 10 px); Ctrl+Z / Ctrl+Y undo and redo; Align, Space across / down and Bring to front / Send to back act on the selection; Delete puts a graphic back at its built-in position.
- **Save layout** stores the boxes on the GoScore server, per sport. `/overlay/live` and every OBS Browser Source pick the change up within a few seconds. Graphics you never moved keep their built-in position.

Positions saved by the editor replace the Production "scorebug position" and "scale" options for that graphic. Single-graphic URLs (`?panel=...`) size themselves to their Browser Source and ignore the layout.

## Cricket slideshow

In Cricket Production, enable **Cricket slideshow panel**, choose the rotation interval, and copy its URL into a separate OBS Browser Source. The slideshow rotates only graphics enabled in the panel controls; the scorebug and event pop-ups remain independent. Keep the slideshow disabled if you prefer to show panels manually.

## Browser Source connections

Individual cricket and football panels use short polling (1.5 seconds) rather than keeping a separate long-lived SSE connection open for each OBS Browser Source. This avoids the common Chromium per-host connection cap that can affect large multi-panel scenes. The practical number of panels still depends on CPU, memory, and rendering load.
