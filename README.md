# record-everything

An agent skill for apps that log every meaningful event, keep the logs cheap, and let AI agents read them reliably.

It was built from [Rat Detective](https://ratdetective.online), a multiplayer browser game. Rat Detective recorded every hit, death, decision and input, for humans and bots alike, and used the data to make its bots play more like people. It also learned what this costs: recording everything in database rows ran to about $16 a day, until storage moved to compressed files in object storage.

The skill has two parts:

- **Guidance** ([SKILL.md](SKILL.md) and [references/](references/)) for the agent building or analysing an app:
  - what to record, in one envelope shared by humans, bots and test agents;
  - how to store it cheaply, and how to check the real bill;
  - how to make bots act through the same controls as humans, so the two can be compared one to one;
  - how to compare builds without fooling yourself.
- **`facts`** ([scripts/facts](scripts/facts)), a read-only command-line tool. It mirrors an app's archive into a local DuckDB file and answers in JSON:
  - an overview;
  - SQL queries;
  - session timelines;
  - a data-quality audit;
  - era comparisons whose intervals resample whole sessions.

Each app describes its data in a `facts.md` file at its root: where the archive is, how to read each fact, and its views, measures, checks and eras.

## Install

You need [uv](https://docs.astral.sh/uv/), which fetches DuckDB the first time `facts` runs.

```sh
git clone https://github.com/MayberryDT/record-everything ~/.agents/skills/record-everything
ln -s ~/.agents/skills/record-everything ~/.claude/skills/record-everything   # Claude Code
ln -s ~/.agents/skills/record-everything/scripts/facts ~/.local/bin/facts     # the tool on PATH
```

## Use

In an app with a `facts.md`:

```sh
facts sync      # fetch new archive objects (resumable)
facts           # overview, warnings and suggested next commands
facts guide     # the handbook for agents
facts check     # data-quality audit
facts compare ERA_A ERA_B
```

For a new app, run `facts init --name my-app`, then follow [references/instrument.md](references/instrument.md). The `facts.md` format is in [references/contract.md](references/contract.md).

## Test

```sh
python3 tests/e2e.py --out /tmp/facts-e2e
```

This serves a fake archive over HTTP and runs the real tool against every case in [tests/FAILURE-MODES.md](tests/FAILURE-MODES.md). It writes a transcript and results file to `--out`.

## License

MIT
