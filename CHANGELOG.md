# Changelog

## 1.0.0 — initial release

- First release version for GoScore cricket scoring, football match management, and OBS graphics.
- Scorebug player names now remain visually blank when no batter or bowler is selected, instead of displaying dash placeholders. The layout slot remains in place so the scorebug does not jump.
- Version metadata aligned to 1.0.0.
- Added a Windows desktop launcher build path so the packaged application can run without a console window.

- Fixed the innings-break action after the first innings of a Super Over pair so the next innings is correctly started as a Super Over, with the one-over default.

## v1.0.0 release-candidate refinements (2026-10-20)

- Football individual OBS panel sources now use the same short-polling strategy as cricket (1.5-second polling with no per-panel long-lived SSE stream), reducing Chromium per-host connection pressure when many panels are open.
- Added a dedicated cricket slideshow Browser Source URL and configurable enable/interval controls. It rotates only production-enabled panels and remains separate from scorebug and event pop-ups.
- Added an optional drag-and-resize layout editor for both sports (`?edit=1`) with per-sport browser-profile persistence and reset controls.
- Added overlay panel size constraints to keep graphics within the 16:9 canvas instead of overflowing its bounds.
- Reused cricket scorebug logo image nodes between score updates to avoid repeated image element creation and visible logo flicker.
- Added regression smoke tests for the new overlay features.

### Overlay layout editor correction (v1.0.0 release candidate)
- Replaced the previous overlay edit mode with the requested split layout editor: a 1920×1080 canvas on the left and a panel checklist on the right.
- Panel checkboxes control preview visibility only; they do not alter Production/broadcast visibility.
- Drag and resize panel graphics on the preview canvas, then save shared geometry through the GoScore server. Saved geometry is read by `/overlay/live` and OBS Browser Sources for the same sport.
- Added validated, atomic persistence for cricket and football layout geometry in the local GoScore data directory.

### Layout editor usability correction
- The editor preview now fits the available space beside the panel checklist while preserving the full 1920×1080 canvas and 16:9 aspect ratio.
- Added representative sample graphics for panels that have no live data, including football and cricket panels, so inactive panels can still be selected, moved, and resized in preview mode.
- Sample graphics are preview-only and do not affect Production visibility or the live broadcast.
- Added container-relative sample typography to reduce clipping when preview panels are resized.
- Existing shared server-side layout persistence continues to apply saved geometry to `/overlay/live` and OBS.

## 1.0.0 layout-scaling correction (2026-10-20)

- Reworked saved overlay geometry to scale complete native graphics uniformly instead of overriding their intrinsic width and height. This preserves scorebug flex columns, table layouts, and typography while resizing.
- Removed global max-width/max-height clamps that were forcing cricket and football panels to shrink internally.
- Kept sample editor panels independently resizable; saved real-panel geometry now maps width to a uniform scale and preserves the original graphic aspect ratio.
- Deferred geometry application for scorebug and event popup containers until their real content has rendered, avoiding an incorrect cached base size during startup.
- Regression checks: 13 focused layout/overlay/Super Over tests passed. Full pytest discovery was attempted but timed out after reaching approximately 65%; full suite is not certified.
