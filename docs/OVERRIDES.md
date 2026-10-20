# Manual override — when software or scorer gets it wrong

Principle: the Laws are enforced by default; **you** are always allowed to correct reality. Everything is logged, reversible and shown in the audit.

## Ladder (use the lightest tool that fixes it)
1. **Undo (Ctrl+Z / U)** — last ball wrong. Redo is available.
2. **Edit** a past ball (Events & corrections → ✎). Everything after it is recalculated.
3. **Delete** a ball, or **Insert after** one (a missed ball, e.g. a wide you forgot) — totals recalc.
4. **Allow anyway** — if a soft rule blocks something real (e.g. a bowler's extra over agreed by the umpires).
5. **Manual override** (tab "Manual override") — pin a number *as of this point in the match*:
   * team: runs, wickets, balls, extras (wide / no-ball / bye / leg-bye / penalty), overs limit, target, wickets limit
   * crease: striker, non-striker, bowler, free-hit on/off
   * any batter: runs, balls, fours, sixes, status/how-out
   * any bowler: balls, runs, wickets, maidens, wides, no-balls
   A reason is required. Later balls keep building on the pinned value. Remove an override and the log recalculates without it.
6. **Manual result** (Match actions) — set the result text/winner yourself.
7. **Raw log replace** — paste a corrected JSON event log (expert use).
8. **Restore backup** — go back to any of the last 100 saved versions.

## Guard rails
* Every action goes to the audit log (what and when, with your reason for overrides).
* Bad events are flagged in red and skipped; they never crash the scoreboard.
* While you fix things, press **H** on the Production page (or *Hold*) so the audience doesn't see the correction in progress.

## Football overrides
Scorer console -> "Manual override": set score (pins; later goals add on top), clock, phase, captain, position, info, final result, abandon, end match. Events tab: edit/insert/delete any event; cancel goal, rescind card. Stats: manual panel. Soft rule warnings can be sent with "Allow anyway".
