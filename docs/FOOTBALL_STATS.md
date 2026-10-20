# Football stats - manual entry guide

There is **no stat scorer page**. Stats are typed by the producer (Production page -> "Match stats (manual)" box, or the scorer's "Stats (manual)" tab) and shown whenever you choose.

Auto-calculated (cannot drift from the log): goals, yellow/red cards, penalties, substitutions, player minutes, player goals/assists. Possession's other side and pass accuracy are derived when you enter one side/passes. Everything auto can still be overridden by typing a value; clearing the field returns it to auto.

Team stats: possession, shots, shots on/off target, blocked, big chances, xG, xGOT, corners, offsides, crosses, dribbles, attacks, dangerous attacks, passes, passes completed, pass accuracy, long passes, fouls, yellow, red, tackles, interceptions, clearances, duels, aerial duels, saves, free kicks, throw-ins, goal kicks, distance.
Player stats: minutes, goals, assists, shots, SOT, xG, xA, key passes, passes, completed, accuracy, touches, dribbles, tackles, interceptions, clearances, duels, fouls committed/won, offsides, cards, saves, goals conceded, distance, rating.

Sanity warnings (e.g. shots on target > shots, completed > passes) show but never block.

## Pages (Production page)
* **Consolidated:** Classic (centered labels + bars), Bars (side-by-side bars), Strip (compact lower-third strip). Choose which rows appear and their order.
* **Individual:** one stat at a time (Possession, Shots, ... any stat) as a lower third, one click each.
* **Player card:** per-player manual stats.
Stat pages use the same publish delay and hold as all graphics.

# One OBS browser source per graphic

Production page -> "One OBS browser source per graphic" lists a URL for every graphic, e.g. `/overlay/<id>?panel=lineups`.
Add each as its own Browser Source with **any** width x height: the graphic scales to fill it (resize the source in OBS and it re-fits).
Options (also settable in the list): `scale=1.2` size multiplier, `align=c|t|b|l|r|tl|tr|bl|br`, `fit=0` (no auto-fit, scale is absolute), `pad=16`, `follow=1` (also obey the Production on/off buttons; default is always visible, so use the OBS eye icon), `stat=shots` (for `panel=stat_single`), `bg=%2300ff00` (test background).
Panels: bug, tracker, popups, lineups, formation_home, formation_away, subs_bench, scorers, timeline, halftime, fulltime, preview, officials, stats_classic, stats_bars, stats_strip, stat_single, player_card, banner.
The old all-in-one `/overlay/<id>` (1920x1080) still works.

# Formation editor (drag and drop)

Scorer console -> "Formation (drag & drop)". Pick a formation (or "custom…"), drag players where they play, press **Save layout**. The formation overlays (`formation_home`/`formation_away`) show exactly that layout.
Substitutions: the player coming on takes the position of the player going off (shown with a green ▲); drag him elsewhere and save again whenever tactics change. Sent-off players leave the pitch. "Reset to formation" forgets dragged positions. Each save is one undoable event (`pitch_set`), works before, during and after the match.
