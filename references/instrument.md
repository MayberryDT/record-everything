# Instrument an app

These rules come from Rat Detective, which recorded everything and then paid about $16 a day for it until the storage was fixed. Follow them from the first commit.

## The envelope

Every fact is one JSON object on one line:

```json
{"kind": "death", "t": 1790837903568, "session": "round-uuid", "build": "production-2026-10-01-4d9e649",
 "actor": "3", "who": "bot", "map": 7, "mind": 6, "victim": "2", "cause": "headshot", "p": [72.7, 0, 111.3]}
```

- `kind`: the event type. `t`: epoch **milliseconds**, server clock. `session`: the episode (match, round or visit).
- `build`: stamped by the deploy script, as `<env>-<date>-<sha>[-dirty]`, never by hand. Deploy from a clean tree.
- `actor`: who did it, numbered per session (1, 2, …). No account ids, names or tokens in facts. If you need cross-session history, keep the account-to-actor mapping in its own access-controlled table.
- `who`: `human`, `bot`, `agent` (automated test browser) or `system`. Set `agent` at connection time from a URL flag (`?agent=1`) and keep it through reconnects. Agents never count as human and never switch on paid AI.
- Add the app's versions that change behaviour: map or layout version, bot-mind version, schema version, mode.
- A fact about two actors names both (`actor`, `victim`). Its `who` describes `actor`.

**Actor numbers must stay stable for the whole session**, across server restarts, sleeps and reconnects. If the recorder can restart inside a session, either persist its actor map with the session or start a new session id. Rat Detective renumbered rats whenever a sleeping room woke inside the same round id, so after 6 October one (round, actor) could name two players. For data already recorded that way, declare the restart fact as `restart_sql` in facts.md, and `facts` keys actors by segment.

## What to record

- Every discrete event that changes state or score: spawns, attacks and their outcome, damage, deaths with cause, pickups, objective changes, purchases, level-ups, joins and leaves, admin commands (`kind: admin`, so the session is excluded).
- **Missed chances**, so behaviour can be measured: an item in reach that was walked past, a shot with no target in sight, a decision that was replaced before it finished.
- A **snapshot** about once a second while a human is connected: the world state and one row per actor (position, health, resources, cooldowns, objective state, what it can see, its standing). This is the shared situation format that bots, analysis and training all read. Write snapshots less often, or not at all, when no human is present.
- **High-rate windows** around the moments that matter, such as from 3 s before to 2 s after damage: per actor position at 5 Hz plus inputs and aim at 20 Hz, the same format for humans and bots. Size the ring buffers for the longest window you keep.
- Bot decisions with the inputs the mind saw, and how each goal ended.
- Client performance every 30 s (fps, frame times, RTT, stalls).
- Sampling is allowed only where volume is extreme and value is low (Rat Detective keeps one bot shot in ten). Mark the fact `sample: 10`.

A feature ships with its facts. Add the new kind to `facts.md` in the same change.

## Storage

```
server (in memory) -> gzip JSONL object every 5 min, every 2 MB and at session end -> object storage (R2, S3)
                                                                                         |
                                                    token-protected list/get endpoints <-+   (facts.md source)
```

- Object storage holds every fact forever. That is the archive, and it is cheap: Rat Detective's 12 days, 3.6 million facts, is 500 MB and cost nothing to store.
- Keys are immutable and time-ordered: `raw/v1/<room>/<YYYY>/<MM>/<DD>/<HH-mm-ss>-<random>.jsonl.gz`. Put `{schema, lines, from, to}` in the object metadata. Count lines that failed to upload and record the count.
- **Do not write a database row per fact.** At most one summary row per session (result, length, roster, build, admin and agent flags).
- If you need live counts (a dashboard, a heat map), pack each flush into one row per bucket, `{key: count}` as JSON. Never one row per key.
- Recording must not change gameplay or eat the tick. Measure the recorder's share of tick time (Rat Detective: 1–3%), and check that a seeded benchmark gives the same trajectory with recording on and off.

## Cost rules

Cloudflare Durable Object SQLite bills **per row**, not per byte: $1 per million rows written after 50 million a month. Rat Detective's $16 a day was almost all rows, written by an empty city that ran all day:

| | Rows written a day (production + staging) |
|---|---|
| 1–5 Oct, always-on bot city, a row per heat cell | 15.7–16.5 million (GameRoom only) |
| 7–8 Oct, after the fixes | 33,000–217,000 |
| 9 Oct, a one-off copy of history to a new room | 14.1 million (about $14) |

- Nothing runs without a human: no tick, no bots, no alarms, no writes. If you want bot-only data, run headless bot batches on a schedule with a fixed budget.
- Write only on change: `ON CONFLICT … DO UPDATE … WHERE value IS NOT excluded.value`.
- Never scan an unindexed column on a hot path. Prune by primary-key range (find the first id to keep, then delete below it), once a day. A `DELETE … WHERE day < ?` without an index read the whole table every minute.
- Any paid AI in the app gets a daily budget enforced by a central ledger that **fails closed**.
- A bulk migration (copying history, rebuilding tables) costs rows too. Estimate it before running it.

## Check the real bill

A local probe estimates; the provider's analytics are the evidence. For Cloudflare, query the GraphQL Analytics API (`durableObjectsPeriodicGroups`: `rowsWritten`, `rowsRead`, `activeTime` by `date` or `datetimeHour` and `namespaceId`). The wrangler OAuth token works. Map namespace ids to scripts with `GET /accounts/{id}/workers/durable_objects/namespaces`. Compare a day before and after any storage change, and explain every spike.

## Done means

Prove it end to end: play a real session (or run a scripted one) on a hosted build, then run `facts sync` and `facts check` from the build host. Check must show no fail findings, every new kind must be listed in `facts.md`, the session must show its humans, bots and agents correctly in `facts session`, and an idle server must write nothing.
