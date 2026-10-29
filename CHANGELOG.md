# Changelog

## 1.0.1 - layout editor and UI changes and fixes

- **The layout editor was rebuilt from scratch.** The 1.0.0 editor drew fake placeholder text instead of the real graphics, injected resize handles into the graphics, let content overflow its box and re-applied styles on every DOM change. The new editor is a small slide editor: selection, multi-selection, marquee, 8-handle resize, snapping with guides, safe-area guides, keyboard nudging, undo / redo, align / distribute, bring to front / send to back, numeric X / Y / W / H, per-graphic reset, unsaved-change warnings.
- **Everything inside a box now scales to fit it.** Cards are stretched to the box and their content scaled to the largest size that fits; the scorebug, shoot-out tracker and pop-ups keep their aspect ratio and are centred. Verified for every graphic of both sports at six different box shapes and sizes (no content outside its box).
- **Sample data now matches what is shown during a real match.** The editor renders the real overlay code from sample matches built by the real cricket and football engines (`goscore/demo.py`): T20 chase in progress, Test day 2 (for the multi-day summary), a finished match (result / summary), football second half, and a penalty shoot-out (tracker). The editor lists the same graphics the overlay really has (the 1.0.0 list contained a "standings" box that does not exist, and used wrong ids for the cricket lower third).
- The live overlay and OBS poll the saved layout every few seconds, so a saved change appears without reloading the Browser Source. Layout saving validates ids and sizes and supports stacking order.
- Fixed: the literal text "null" appeared in cricket graphics (innings summary and others) when an optional block was empty.
- Fixed: football graphics showed the word "Football" where an icon was meant (scorers, timeline, scorer console buttons), and shoot-out kicks printed overlapping "Scored" / "Missed" words instead of marks.
- Fixed: cricket "Over by over" labels ("Over 15") wrapped onto two lines.
- Removed the 1.0.0 rules that made panels scroll (`overflow:auto`) and shrink to `100% - 32px`.
- `?sport=cricket|football` can be added to an overlay URL to open the editor before any match exists.

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
