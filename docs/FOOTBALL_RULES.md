# Football rules in GoScore (v1.1)

Basis: IFAB Laws of the Game (Law 3 players/substitutions, Law 10 determining the outcome, Law 12 cards, concussion-substitution protocol), plus common competition formats.

## Hard vs soft rules
* **Hard** rules are rejected (HTTP 422): impossible things such as a goal before kick-off, a substitution of a player who is not on the pitch, a card to a player not in the squad, a second shoot-out kick after the shoot-out is decided.
* **Soft** rules warn and can be sent again with "Allow anyway" (`force:[code]`): substitution/window limits, a returning substituted player (unless the format allows return subs), a shoot-out taker kicking twice in a cycle, a taker not on the pitch. Competitions differ, so the producer has the last word.

## Time
Server-authoritative clock. Phases: pre, 1st half, half-time, 2nd half, full-time/ET break, ET 1, ET break, ET 2, pre-shoot-out, shoot-out, ended. Event minutes are stamped when the event is added (inserting or editing later does not shift them). Added time is announced with the "Added time" control and shows as +N on the bug.

## Cards
Second yellow = red (counts as dismissal), a sent-off player cannot be booked again or replaced, bench and staff cards are supported, VAR can rescind a card.
Convention: the **yellow cards** stat counts yellows shown; **red cards** counts dismissals (straight red + second-yellow). Override either manually in the stats panel.

## Shoot-out
Early finish when a side cannot catch up within its 5 kicks; after 5 each it is decided only after equal kicks; every eligible player kicks once per cycle (soft).

## Not supported
Away-goals rule (abolished by UEFA); aggregate is by total goals then extra time/penalties. Anything else: use the override panel (score, clock, phase, result, abandon).
