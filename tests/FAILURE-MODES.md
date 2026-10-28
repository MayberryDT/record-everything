# How `facts` can fail

This list was written before the code. `tests/e2e.sh` covers every case marked [e2e]. The rest were checked against Rat Detective's real archive.

## Contract
1. No `facts.md` in this directory or any parent → exit 2, naming `facts init` and the directories searched. [e2e]
2. The front matter is missing or invalid YAML, or `source` is missing or of an unknown kind → exit 2, naming the key. [e2e]
3. A field mapping is invalid SQL → exit 2, naming the field, before anything is ingested. [e2e]
4. A contract view has bad SQL → it is reported as broken, and every other command keeps working. [e2e]

## Source and sync
5. The token file is missing → exit 4, naming the file and the env var. The token is never printed. [e2e]
6. The source answers 401 or 403 → exit 4 at once, saying the token was rejected. [e2e]
7. The source fails transiently (5xx, 429, timeout) → retried with backoff; after the last attempt, exit 4 saying a rerun resumes. [e2e]
8. A sync is interrupted → a half-downloaded file is never ingested (written as `.part`, then renamed). An object is marked done in the same transaction as its facts. A rerun fetches only the rest. [e2e]
9. A corrupt gzip object → that object is recorded as failed and the others still ingest. Exit 4; `check` fails until a rerun succeeds. [e2e]
10. Malformed JSON lines → counted per object, never silently dropped; `check` warns. [e2e]
11. The field mapping changes after ingest → `facts` and `check` warn until the next sync, which rebuilds from the local raw files without downloading (`--rebuild` forces it). [e2e]
12. Two syncs at once, or a query during a sync → exit 6 (busy) with what to do. [e2e]

## Reading
13. Nothing synced yet → bare `facts` succeeds and says to run `facts sync`; other commands exit 3 with that command. [e2e]
14. The SQL changes data → refused, because the database is opened read-only. [e2e]
15. The SQL is wrong → exit 1 with DuckDB's message and the command that lists tables. A JSON arrow written after AND/OR/NOT without parentheses (DuckDB binds it wrongly and raises a conversion error) → the error says how to write it. [e2e]
16. A huge result → capped at `--limit`, marked `truncated`, with the command that gets more. [e2e]
17. Admin-touched sessions or test-agent facts leak into the default `facts` view → they must not; `all_facts` keeps them. [e2e]
18. A fact about two actors has no `who` → classified through the actor's other facts in the same session. [e2e]
19. Unknown command or flag typo → exit 1 with the closest correct command. [e2e]
20. Unknown kind, era or session → exit 1 listing the closest matches. [e2e]
21. Too little data to compare → the verdict is `not enough data`, never a bare number. [e2e]
22. Times recorded in seconds instead of milliseconds, or in the future → `check` fails. [e2e]
23. stdout gets a progress line, color or a prompt → never; stdout is one JSON document (or `--table` text), and diagnostics go to stderr. [e2e]
24. The sync is killed (out of memory, hangup) after ingesting but before rebuilding `sessions` and `actors` → triage warns `derive-stale` until a sync completes. DuckDB is capped at a quarter of RAM (`FACTS_MEMORY`) and spills to the cache, because its default of 80% got the process killed on a 16 GB build machine. (Found on Rat Detective's real archive; not in the e2e.)

## Found by a fresh agent using the tool on Rat Detective (all [e2e] now)
25. The app reuses actor numbers inside a session after a restart → with `restart_sql`, actors are keyed by session segment, and a reused number gets its new class after the restart.
26. A two-actor fact (a hit, a death) needs the other party's class → `target` / `target_who`, resolved in the same segment.
27. "Hours" of a session include idle and sleeping time → triage reports `play_hours` from the contract's `exposure`, not session spans.
28. Events bunch up inside sessions, so per-event intervals are too narrow → a measure that returns a `session` column gets a bootstrap interval over whole sessions and a minimum number of sessions. Others are labelled as assuming independent events.
29. `--help` crashed: argparse read "95% intervals" as a format code.
30. SQL sent over ssh loses its quotes → `--file PATH` and `-` (stdin).
31. The JSON-arrow hint appeared on unrelated errors → it is shown only when an arrow follows AND/OR/NOT.
32. Builds that no era covers cannot be compared by name → `check` lists them.
33. Archive objects flushed in the same second sort by their random suffix, not by time, so a restart can be ingested after facts that follow it → each sync recomputes segments from the complete restarts table. (Found on Rat Detective's archive.)
34. The difference interval paired the two eras' bootstrap draws after sorting them, which made it far too narrow (it showed ±13 where one side alone spanned ±23) → draws are paired unsorted, and the e2e checks that the difference interval is at least as wide as either side's half-width.
35. A `dir` source's `.jsonl` that grows (an append-only event log) was never re-read: sync skipped any key it had seen, despite the contract's size rule → a key whose listed size changed is re-ingested, and its old rows are replaced, not duplicated. (Found on the marketing repo's `state/events.jsonl`.) [e2e]
36. A `dir` source was deleted (it lived in a scratch build directory) and `facts` kept answering from its cache with no sign the data could no longer be refreshed → a missing `dir` source is a fail-level `source-missing` warning in triage and `check`. (Found on Siege of Champions.) [e2e]
37. The cache stored each fact's raw JSON uncompressed, so it was larger than the gzip archive's raw bytes (about 300 MB per 30-minute Siege match), and sync committed once per object at 50 to 250 ms a commit (two minutes per match) → new caches use DuckDB storage v1.2 with zstd (about 15 times smaller, same query speed), and sync commits 256 objects at a time, retrying a failed batch one object at a time so only the bad object is recorded. (Found on Siege of Champions.) [e2e: zstd]
