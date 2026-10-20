# GoScore cricket scoring — bug audit

## Read this first (honest caveat)
The `GoScore_AppCode.zip` you supplied contained the **scoring core only** (`poc_core` bytecode plus a few helpers).
It did **not** contain `server.py`, `results.py` or the `frontend/src` code. So:

* Every bug below was **reproduced by running the original scoring code** (`tests/legacy_bug_probe.py` runs it against `legacy/poc_core.py`). None are guesses.
* I could **not** see what the original frontend actually sends, so I cannot say which of these a scorer would have hit through the old UI.
  Where the engine needs a field the old payloads may not have supplied (bug 1), the failure is real in the engine either way.
* The new app is therefore a **standalone replacement** (new engine + server + web UI), not a patch to the old repo. The old repo is left untouched in `legacy/`.

Re-run the evidence any time: `python tests/legacy_bug_probe.py` (old code) and `python -m unittest discover -s tests` (new code, 62 tests).

## Bugs found in the old cricket scoring

| # | What goes wrong (reproduced) | Why it matters | Fix in new engine | Covered by test |
|---|---|---|---|---|
| 1 | A single off the bat does **not** change the strike unless a separate `ran` field is supplied; after 1 run, striker is still A1. | Wrong batter shown facing, wrong runs credited from then on. | Strike change is derived from runs actually run (`ran` only overrides, e.g. overthrows). | `test_bug01_*`, `test_three_runs_*` |
| 2 | Maiden overs are **never counted** (6 dots → 0 maidens). | Wrong bowling figures. | Maidens computed per over: zero runs off bat/wides/no-balls charged (byes/leg-byes allowed). | `test_bug02_*`, `test_maiden_allows_byes` |
| 3 | Wide with `extra_type=bye` + 2 runs is booked as wide 3 **and** bye 2 (5 total). | Wrong total. A wide plus runs is all wides; byes cannot be scored off a wide per the Laws as applied here. | Wide runs all go to wides; bye-on-wide is rejected. | `test_bug03_*`, `test_bug03b_*` |
| 4 | 1 bye + 1 overthrow booked as a **penalty** run. | Wrong extras category. | Runs after a bye are byes; penalty runs only via the explicit penalty action. | `test_bug04_*` |
| 5 | "Caught" off a no-ball and "bowled" off a wide are accepted as wickets. | Illegal dismissals — outside the Laws. | Dismissals allowed per delivery type: legal = all; no-ball = run out / hit twice / obstructing; wide = run out / stumped / hit wicket / obstructing. Rejected otherwise. | `test_bug05_*`, `test_run_out_and_obstructing_*` |
| 6 | Retired hurt marks the batter **out**, adds a phantom ball, and consumes a legal ball. | Wrong wicket count, wrong ball count. | Retired hurt = not out, may return, uses no ball. Retired out = wicket (not credited to bowler). | `test_bug06_*`, `test_retired_out_*` |
| 7 | Dismissal text is wrong: "run out F1 b B1", "timed out b B1" (bowler appended to non-bowler dismissals), "c&b b B1". | Wrong scorecard text on air. | Per-kind text: `c F b B`, `c & b B`, `run out (F)`, `timed out`, etc. | `test_bug07_*` |
| 8 | Right after the 6th legal ball `this_over` is empty (0 balls) and the over has already flipped. | The "this over" chips disappear the instant an over ends. | Completed over stays displayed until the next ball; over/bowler prompt shown. | engine `this_over` tests / UI |
| 9 | Result line is wrong: "Innings complete" when the chase falls 1 short or ties; hard-coded **10** wickets for all out. | Wrong result text; breaks any team that isn't 11. | Results: win by N wickets (balls left), win by N runs, tie, super-over, DLS tag. All-out = players − 1 (configurable). | `test_bug09_*`, `test_chase_won_*` |
| 10 | Balls are accepted **after the overs limit** (2-over match reached 2.2). | Illegal — innings must end. | Innings auto-ends at overs limit / all out / target reached; extra balls rejected. | `test_bug10_*` |
| 11 | XML export **crashes / is invalid** when real data is present (a player name produced "not well-formed" XML). | OBS/vMix XML feed breaks. | XML builder sanitises tag names and escapes text; validated by tests. | `test_api` XML test |
| 12 | Bowled on a **free-hit** delivery counts as a wicket. | Illegal — only run out / hit twice / obstructing on a free hit. | Free hit enforced, and carries over wides and further no-balls. | `test_bug12_*`, `test_free_hit_*` |
| 13 | The "adjustment" event changes team runs but not batter/extras, so **totals stop reconciling**. | Scorecard doesn't add up. | Replaced by the **Override layer** (see `OVERRIDES.md`) which is explicit, reasoned, audited and keeps the rest consistent. | `test_override_*` |
| 14 | Same bowler can bowl consecutive overs; no per-bowler quota. | Outside competition rules. | Quota (default ceil(overs/5)) and no-consecutive-overs enforced as **soft** rules: scorer sees why and may "Allow anyway" (logged). | `test_bug14_*` |
| 15 | Dismissing a player who is not at the crease is accepted (and the wrong batter stays). | Corrupt state. | Only the two batters at the crease can be out (run-out) / only the striker for striker-only kinds. | `test_bug15_*`, `test_striker_only_*` |

### Not a bug in one line, but a structural weakness (fixed by design)
* **Contract mismatch:** the engine and its own test payloads did not agree on field names (e.g. `ran`, extras shape). The new engine has one documented ball schema used by the UI, the API and the tests.
* **No safe way to correct mistakes:** the old design could only append. The new design stores the **event log** as the source of truth and replays it; you can undo/redo, edit, delete, insert-after, replace the raw log, restore any of the last 100 backups, or pin any number with a manual override.
* **No crash safety:** writes are atomic (temp file + rename, retried on Windows file locks), every change is journalled, and a bad event is flagged and skipped instead of taking the scorebug down.

## What to do to fix it (if you keep the old repo)
You can't "patch" the old zip reliably without the missing server/frontend, so the practical route is:
1. Use this new app for Sunday (it is self-contained, standard-library Python, no install).
2. If you later want the new engine inside the old repo, `goscore/engine.py` exposes just two functions — `derive(match)` and `validate_append(match, event)` — and a documented event schema (`docs/CRICKET_RULES.md`). Wire your server to call those and delete the old ball-handling code.
3. Keep `tests/` — they are the specification.

## Known limits of the new code
* Verified: engine (55 tests), API/persistence/feeds (7 tests), scorer UI, overlay, control page and scene switching in headless Chromium.
* **OBS control was tested against a mock obs-websocket server, not real OBS.** Do the rehearsal in the runbook.
* DLS is **not computed** — you enter the revised target/overs from your DLS source (manual by design; the Laws don't change).
* Football is not implemented (as requested). Multi-day is basic (two innings a side, no follow-on).
* Default powerplay / bowler-quota values are standard ICC-style defaults; check them against **your competition's playing conditions** and edit them on the match Setup page if they differ.
