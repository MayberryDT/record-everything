# facts.md: the contract

`facts.md` sits at the app's root. Its YAML front matter is read by `facts`. Its Markdown body is for agents: write what a reader needs that the data cannot say (known bugs by date, sampling, retired kinds, how sessions map to play). `facts init --name APP` writes a starting file. Rat Detective's file is a full example.

## Front matter

| Key | Required | Meaning |
|---|---|---|
| `facts` | yes | Contract version: `1`. |
| `name` | yes | Lowercase app name; it names the cache (`~/.cache/facts/NAME`). |
| `source` | yes | Where the archive is (below). |
| `environment` | no | e.g. `production`. Eras from another environment are refused by `facts compare`. |
| `fields` | no | How to read the envelope from each raw fact (below). |
| `admin_kinds` | no | Kinds that mark a session as admin-touched. Default `[admin]`. |
| `actor_sql` | no | Extra SQL giving `(session, segment, actor, who)` rows for labelling actors, e.g. from snapshot frames. It runs over `facts_all` at each sync; leave out `segment` if there is no `restart_sql`. |
| `restart_sql` | no | A condition over the stored columns (`kind`, `t`, `session`, `actor`, `target`, `who`, `data`) marking facts after which the app renumbers actors inside the same session. Each such fact starts a new **segment**; actors are keyed by `(session, segment, actor)`. |
| `exposure` | no | SQL over a relation named `source` returning `session, who, hours` of actual play. It becomes the `exposure` view (over `facts`), `era_exposure` in measures, and `play_hours` in triage. |
| `bulky` | no | Kinds left out of `facts session` timelines unless asked for (snapshots, input windows). |
| `sessionless` | no | Kinds that legitimately have no session, so `check` does not count them as missing one. |
| `kinds` | no | `kind: one-line meaning`, or `kind: {about, fields: [...]}`. Once set, `check` and `schema` report kinds recorded but not listed, listed but never recorded, and (with `fields`) field drift. |
| `views` | no | `name: SQL`. Temporary views created on every run, so they always match this file. A broken view is reported, not fatal. |
| `measures` | no | `name: {about, rate: SQL}` or `{about, share: SQL}` for `facts compare` (below). |
| `checks` | no | `name: {about, level: warn|fail|info, sql}`. Every row the SQL returns is a problem; `check` shows the count and five rows. |
| `eras` | no | A list of `{id, from, to, build, environment, change}`, or a path to a JSON file holding one (or `{eras: [...]}`). |
| `minimums` | no | `{events: 20, exposure_hours: 0.5, sessions: 5}`: below these, a verdict is `not enough data`. |
| `fresh_hours` | no | Warn when the newest fact is older than this. |
| `budget` | no | `{archive_mb_per_day: N}`: `check` warns on days above it. |
| `cache` | no | Cache directory, relative to this file. `FACTS_CACHE` overrides it. |

## The source

**http** (recommended for deployed apps): two token-protected endpoints that the app serves from its object storage.

```yaml
source:
  kind: http
  list: https://app.example/api/facts/v1/archive?prefix=raw/v1/   # GET -> {"objects": [{"key", "size"}], "cursor"?}
  get: https://app.example/api/facts/v1/archive/{key}           # GET -> the gzip bytes; {key} is URL-encoded
  token_env: APP_FACTS_TOKEN          # read first, if set
  token_file: ~/.config/app/facts-token
```

`list` pages with `&cursor=` until a page has no `cursor`. Both endpoints get `Authorization: Bearer <token>`. Keys must be immutable: a key is fetched once and never again unless its listed size changes. 401 and 403 stop the sync; 5xx, 429 and network errors are retried.

**dir**: `{kind: dir, path: ./archive}`, which ingests every `*.jsonl.gz` and `*.jsonl` under the path in place. Use it for local or exported archives.

## Fields

Each core column comes from the raw fact. A bare name or dotted path (`round`, `ctx.build`) reads that JSON field. Anything else is a DuckDB SQL expression over the raw fact, named `json`. The defaults match the recommended envelope:

```yaml
fields:            # defaults
  kind: kind
  t: t             # epoch milliseconds
  session: session
  build: build
  actor: actor     # who did it
  target: target   # the other party (a victim), if any
  who: who         # human | bot | agent | system
```

Changing `fields`, `admin_kinds` or `actor_sql` makes the next sync rebuild from the local raw files (no downloads).

## Tables and views

- `facts_all`: stored rows: `object, kind, t, ts, session, segment, build, actor, target, who, data` (`data` is the whole raw fact as JSON).
- `actors`: `session, segment, actor, class, seen_as`. The class is `agent` if the actor was ever a test agent, else human, else bot.
- `sessions`: `session, first_t, last_t, started, hours, facts, segments, builds, admin, humans, bots, agents`. `hours` is the span from first to last fact, and a session can include idle time. `humans` counts actor slots, not people.
- `objects`: archive objects with `lines`, `bad_lines` and `error`.
- `all_facts`: `facts_all` with `who` and `target_who` resolved through `actors`, plus `day` and `admin_session`.
- `facts`: `all_facts` without admin-touched sessions or test-agent facts. Analyse here.

## Measures

`facts compare A B` creates the views `era` (the `facts` rows of that era), `era_sessions` (`session, hours` inside the era) and, with `exposure`, `era_exposure`. Then it runs each measure:

- `rate:` returns `n` (a count, or a sum such as damage points; say which in `counts:`) and `exposure` (hours, or minutes with `per: minute`).
- `share:` returns `k` and `n`.
- **Return a `session` column, one row per session.** The measure is then clustered: the 95% interval resamples whole sessions, and the verdict needs the difference's interval to exclude zero and at least `minimums.sessions` sessions with exposure on each side. Events bunch up within sessions, so without this a handful of sessions can look like a certain change.
- With a single total row, the interval is Poisson (rate) or Wilson (share), which assumes independent events, and the result says so.

`facts measures` prints each measure's SQL.

```yaml
measures:
  human-deaths-per-human-hour:
    about: deaths of humans per hour of human play
    rate: >-
      SELECT e.session, coalesce(d.n, 0) AS n, e.hours AS exposure
      FROM (SELECT session, hours FROM era_exposure WHERE who = 'human') e
      LEFT JOIN (SELECT session, count(*) AS n FROM era WHERE kind = 'death' AND target_who = 'human' GROUP BY 1) d
      USING (session)
```

Use exposure that counts actual play, such as 1 Hz snapshot rows per human; session spans include idle time. With no `measures`, `compare` reports each kind per session-hour (clustered), which is only a rough first look.

In DuckDB, put a JSON arrow in parentheses inside `AND`, `OR`, `NOT` or arithmetic: `... AND (data->>'$.x') = 'v'`.
