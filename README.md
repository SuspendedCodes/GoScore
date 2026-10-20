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

## Tests

Run the tests from the source folder with `python -m unittest discover -s tests`.

## Release note

This is GoScore v1.0.0, the initial release. Rehearse with practice matches before using it for a live broadcast and report reproducible issues with the GoScore version and relevant logs.

## Overlay layout editor

Open the match overlay in a browser with `?edit=1` appended to its URL (for example, `/overlay/MATCH_ID?edit=1`). Use **Arrange overlay layout** on the Production page to open it directly. Drag a graphic to move it and drag its blue bottom-right handle to resize it. **Reset layout** removes saved positions; **Done** returns to the normal overlay. Cricket and football layouts are saved separately in the browser profile that is rendering the overlay. If you want to edit from OBS itself, open the editor URL in an OBS Browser Source using the same profile.

## Cricket slideshow

In Cricket Production, enable **Cricket slideshow panel**, choose the rotation interval, and copy its URL into a separate OBS Browser Source. The slideshow rotates only graphics enabled in the panel controls; the scorebug and event pop-ups remain independent. Keep the slideshow disabled if you prefer to show panels manually.

## Browser Source connections

Individual cricket and football panels use short polling (1.5 seconds) rather than keeping a separate long-lived SSE connection open for each OBS Browser Source. This avoids the common Chromium per-host connection cap that can affect large multi-panel scenes. The practical number of panels still depends on CPU, memory, and rendering load.

### Arrange the live overlay

Open the match overlay with `?edit=1` appended to its URL (for the live match, `/overlay/live?edit=1`). The editor shows the 1920×1080 preview on the left and a panel checklist on the right. Checkboxes only control what is visible while arranging the preview; they do not switch panels on or off in Production. Drag a panel to reposition it, drag its lower-right handle to resize it, then choose **Save layout**. The saved geometry is stored by the local GoScore server and is applied to `/overlay/live` and OBS Browser Sources for that sport. **Done** exits the editor. Layout Reset clears the saved geometry for that sport.
