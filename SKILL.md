---
name: record-everything
description: Record an app's events as facts that agents can read cheaply, and read them with the `facts` tool. Use to instrument an app's telemetry, answer questions from a project's recorded data (it has a facts.md), compare builds or eras, design bots that play like humans from that data, or audit data quality and telemetry cost.
---

# Record everything

An app that follows this skill writes every meaningful event as a **fact**: a gzipped JSON line in cheap object storage, with one envelope shared by humans, bots and test agents. Its root `facts.md` says where the facts are and how to read them, and `facts` (this skill's read tool) mirrors them into a local DuckDB file for querying. Rat Detective (ratdetective.online), a multiplayer browser game, was the first app built this way.

## Choose the operation

| Task | Do this |
|---|---|
| Answer a question from an app's data | In the project, run `facts`. It returns an overview with the next commands. `facts guide` is the handbook. Never hand-parse the archive or query production. |
| Add recording to an app, new or existing | Read [references/instrument.md](references/instrument.md), then write `facts.md` (`facts init --name APP`, format in [references/contract.md](references/contract.md)). |
| The app has bots or AI agents acting in it | Also read [references/ai-actors.md](references/ai-actors.md). |
| Judge a change, compare builds or eras, design measures | Read [references/analysis.md](references/analysis.md); run `facts compare`. |
| Audit data quality or telemetry cost | Run `facts check`, then the cost section of [references/instrument.md](references/instrument.md#check-the-real-bill). |

## Rules for every operation

- Humans come first. The `facts` view already leaves out test agents and admin-touched sessions; keep them out of conclusions about players.
- Every claim gives its size (events, exposure hours), its era or build, and the `facts` command that reproduces it. `facts compare` reports `up` or `down` only when 95% intervals separate.
- Sync and query on a build machine with disk to spare, not a laptop home directory: a mirror can reach gigabytes.
- `facts.md` is the single maintained description of an app's data. Promote a query you needed twice into a view, measure or check there. When the recorder changes, update `kinds` and add an era, so the next agent starts further ahead.
- A feature is not finished until it records its facts.

## The tool

`scripts/facts`, also installed as `facts` on PATH. It runs through `uv`, which fetches DuckDB on first use. `facts capabilities` gives the commands, exit codes and JSON envelope. Its end-to-end test is `python3 tests/e2e.py --out DIR`, which serves a fake archive and covers every case in [tests/FAILURE-MODES.md](tests/FAILURE-MODES.md). Run it after changing the tool.

When you finish, report what you ran, what it showed (with its size and era) and anything left unchecked.
