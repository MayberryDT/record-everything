# Analysis: eras, measures and honest verdicts

## Eras

An era is a span in one environment in which nothing that affects play changed. Every deploy that changes play starts one. Keep them in `facts.md` `eras` (or a JSON file it points to):

```json
{"id": "softer-bots", "environment": "production", "build": "production-2026-10-10-21177b7",
 "from": "2026-10-10T00:39:43Z", "to": null, "change": "20% longer bot reaction delays",
 "baseline": "chaos-evidence",
 "predictions": [{"says": "bots deal less damage to humans", "measure": "bot-damage-to-humans-per-human-hour", "expect": "down"}]}
```

Write predictions before the data arrives, and name a measure from `facts.md`. Then judge them with `facts compare BASELINE ERA --measure NAME`. A build list covers presentation-only deploys that share one era.

## Measures

- Count human exposure from what humans actually did, such as 1 Hz snapshot rows of human actors divided by 3600. Session spans include idle and sleeping time: Rat Detective's rounds with a human span 106 hours, but human snapshots add up to 9 human rat-hours.
- Rates per hour of exposure, and shares for k-of-n outcomes. Undo sampling weights (`sample: 10` counts ten).
- Keep human, bot and agent numbers apart. Report humans first.
- A measure whose two eras disagree on something irrelevant is wrong; fix the measure before trusting it. Rat Detective's first bot-decision rate mixed 1 s and 5 s snapshots and made a flat rate look like a 2.6× rise.

## Verdicts

Write measures per session (return a `session` column). Events bunch up inside sessions: one long round with a strong player can carry an era. A clustered measure's interval resamples whole sessions, and `facts compare` calls `up` or `down` only when the interval of the difference excludes zero and both sides meet the minimums (default 20 events, 0.5 exposure hours, 5 sessions). Otherwise it reports `no clear change` or `not enough data`. Repeat those words; never present a bare number as a change. Mention the exposure and the number of sessions behind every claim.

A fresh agent's first review of Rat Detective's data showed why. Treating hits as independent events and trusting reused actor numbers produced a confident "bots deal 62% more damage to humans" between two eras. With classes resolved per segment and rounds resampled, `facts compare` gives 275 against 355 damage per human-hour: a difference of +80 with an interval from −82 to +195, from 4 and 13 rounds. That is `not enough data`, not a 62% rise.

## Pitfalls seen in real data

- **Actor ids reused within a session.** If the app renumbers actors when it restarts inside a session, set `restart_sql` in facts.md, so actors are keyed by segment and `who`/`target_who` stay right. `facts check` flags any remaining actor recorded as both human and bot. Totals the app itself keeps per session (K/D/A, standings) still restart with each segment; fix the recorder.
- **World counts that include test agents.** Rat Detective's `world.humans` counts agent browsers. Classify actors through `actors`, not through the app's own counts.
- **Most data may be bots.** An always-on bot world produces most of the volume (Rat Detective: about 1,230 bot rat-hours against 9 human rat-hours in 12 days). Compare on human exposure, and expect totals to collapse when bot-only play stops.
- **Recorder bugs have dates.** Write them in the `facts.md` body, for example "every death before 07:24 UTC on 29 September was filed as missile", so later agents do not rediscover them.

## Making it accretive

When an analysis needs a query twice, add it to `facts.md` as a view, measure or check, so it runs every time and the next agent starts from it. When a check finds a recorder bug, keep the check after the fix: it proves the fix and catches regressions. When a finding drives a design change, ship the change as a new era with its prediction, then judge it.
