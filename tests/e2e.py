#!/usr/bin/env python3
"""End-to-end test of `facts` against a fake app archive served over HTTP.

Covers every [e2e] case in FAILURE-MODES.md. Writes a transcript of every command and a
results file to --out (default: a new temp directory), then exits 0 only if every case passed.

    python3 tests/e2e.py [--out DIR]
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

FACTS = Path(__file__).resolve().parent.parent / "scripts" / "facts"
TOKEN = "e2e-secret-token"
DAY = 1_790_000_000_000  # 2026-09-21
H = 3_600_000


def fact(kind, t, session, build, **extra):
    return {"kind": kind, "t": t, "session": session, "build": build, **extra}


def build_archive(root: Path) -> dict[str, bytes]:
    """Objects keyed like a real archive. Returns key -> gzip bytes."""
    objects = {}

    def put(key, lines):
        objects[key] = gzip.compress(("\n".join(lines) + "\n").encode())

    # Era 1 (build b1): two ordinary sessions with a human and a bot, few deaths.
    lines = []
    for s, start in (("s1", DAY), ("s2", DAY + 2 * H)):
        lines += [json.dumps(fact("spawn", start, s, "b1", actor="1", who="human")),
                  json.dumps(fact("spawn", start + 1, s, "b1", actor="2", who="bot"))]
        for i in range(10):
            lines.append(json.dumps(fact("shot", start + 1000 * i, s, "b1", actor="1", who="human")))
            # damage carries no `who`: its class must come from the actor's other facts
            lines.append(json.dumps(fact("damage", start + 1000 * i + 5, s, "b1", actor="1", target="2")))
        for i in range(25):
            lines.append(json.dumps(fact("death", start + 60_000 * i, s, "b1", actor="2", target="1", cause="shot")))
        lines.append(json.dumps(fact("end", start + H, s, "b1")))
    lines.append(json.dumps(fact("shot", DAY + 3000, "s1", "b1", actor="2", who="human")))  # actor id reused, no restart
    # s2 restarts its actor numbers half way: actor 7 is a bot before the restart and a human after it
    s2 = DAY + 2 * H
    lines += [json.dumps(fact("spawn", s2 + 1000, "s2", "b1", actor="7", who="bot")),
              json.dumps(fact("death", s2 + 10 * 60_000, "s2", "b1", actor="1", target="7", marker="before")),
              json.dumps(fact("restart", s2 + 30 * 60_000, "s2", "b1")),
              json.dumps(fact("spawn", s2 + 31 * 60_000, "s2", "b1", actor="7", who="human")),
              json.dumps(fact("death", s2 + 40 * 60_000, "s2", "b1", actor="2", target="7", marker="after"))]
    lines.append("{this is not json")
    put("raw/2026/09/21/a.jsonl.gz", lines)

    # Era 2 (build b2): many more deaths per hour, an admin-touched session and a test agent.
    lines = []
    for s, start in (("s3", DAY + 5 * H), ("s4", DAY + 7 * H)):
        lines += [json.dumps(fact("spawn", start, s, "b2", actor="1", who="human"))]
        for i in range(120):
            lines.append(json.dumps(fact("death", start + 30_000 * i, s, "b2", actor="2", target="1", cause="shot")))
        lines.append(json.dumps(fact("end", start + H, s, "b2")))
    lines += [json.dumps(fact("spawn", DAY + 9 * H, "s5", "b2", actor="1", who="human")),
              json.dumps(fact("admin", DAY + 9 * H + 10, "s5", "b2", command="end-round")),
              json.dumps(fact("death", DAY + 9 * H + 30 * 60_000, "s5", "b2", actor="2", target="1")),
              json.dumps(fact("spawn", DAY + 5 * H + 50, "s3", "b2", actor="9", who="agent")),
              json.dumps(fact("shot", DAY + 5 * H + 60, "s3", "b2", actor="9", who="agent")),
              json.dumps(fact("shot", DAY + 5 * H + 70, "s3", "b2", actor="9", who="human")),  # conflicting label
              json.dumps(fact("perf", 1_790_000_000, None, "b2", fps=60)),  # seconds, not ms
              json.dumps(fact("mystery", DAY + 5 * H + 80, "s3", None)),  # undeclared kind, no build
              json.dumps(fact("spawn", DAY + 5 * H + 90, "s3", "b3", actor="4", who="bot"))]  # a build no era covers
    put("raw/2026/09/21/b.jsonl.gz", lines)
    objects["raw/2026/09/21/c-corrupt.jsonl.gz"] = b"this is not gzip at all"
    # Two objects flushed in the same second: the one holding the restart sorts after the one holding a later fact.
    s7 = DAY + 12 * H
    put("raw/2026/09/21/e-a.jsonl.gz", [json.dumps(fact("spawn", s7 + 10, "s7", None, actor="5", who="human"))])
    put("raw/2026/09/21/e-b.jsonl.gz", [json.dumps(fact("spawn", s7 - 10, "s7", None, actor="5", who="bot")),
                                        json.dumps(fact("restart", s7, "s7", None))])
    put("raw/2026/09/21/d-flaky.jsonl.gz", [json.dumps(fact("spawn", DAY + 11 * H, "s6", "b2", actor="3", who="bot"))])
    return objects


class Archive(http.server.BaseHTTPRequestHandler):
    objects: dict[str, bytes] = {}
    flaky_left = 1
    gets = 0

    def log_message(self, *args):
        pass

    def send(self, code, body: bytes, kind="application/json"):
        self.send_response(code)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("authorization") != f"Bearer {TOKEN}":
            return self.send(401, b'{"error":"unauthorized"}')
        url = urllib.parse.urlsplit(self.path)
        params = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/list":
            keys = sorted(self.objects)
            start = int(params.get("cursor", 0))
            page = keys[start:start + 2]  # two per page: exercises pagination
            body = {"objects": [{"key": k, "size": len(self.objects[k])} for k in page]}
            if start + 2 < len(keys):
                body["cursor"] = str(start + 2)
            return self.send(200, json.dumps(body).encode())
        if url.path.startswith("/get/"):
            key = urllib.parse.unquote(url.path[5:])
            if "flaky" in key and Archive.flaky_left:
                Archive.flaky_left -= 1
                return self.send(503, b"try later")
            if key not in self.objects:
                return self.send(404, b'{"error":"not found"}')
            Archive.gets += 1
            return self.send(200, self.objects[key], "application/gzip")
        self.send(404, b"{}")


CONTRACT = """---
facts: 1
name: e2e-app
environment: test
cache: .cache
source:
  kind: http
  list: {base}/list
  get: {base}/get/{{key}}
  token_file: {token_file}
admin_kinds: [admin]
restart_sql: kind = 'restart'
exposure: SELECT session, 'human' AS who, (max(t) - min(t)) / 3.6e6 AS hours FROM source WHERE session IS NOT NULL GROUP BY session
sessionless: [perf]
bulky: [shot]
kinds:
  spawn: an actor enters play
  shot: a trigger pull
  damage: a hit lands
  death: an actor dies
  end: a session ends
  restart: actor numbers restart
  admin: an admin command
  perf: client frame stats
  never: declared but never recorded
views:
  human_deaths: SELECT * FROM facts WHERE kind = 'death' AND (data->>'$.target') = '1'
  broken_view: SELECT nope FROM nowhere
measures:
  deaths-per-session-hour:
    about: deaths per hour of play, clustered by session
    rate: >-
      SELECT e.session, coalesce(d.n, 0) AS n, e.hours AS exposure
      FROM (SELECT session, sum(hours) AS hours FROM era_exposure GROUP BY session) e
      LEFT JOIN (SELECT session, count(*) AS n FROM era WHERE kind = 'death' GROUP BY session) d USING (session)
  deaths-flat:
    about: deaths per session-hour, not clustered
    rate: SELECT count(*) FILTER (kind = 'death') AS n, (SELECT coalesce(sum(hours), 0) FROM era_sessions) AS exposure FROM era
checks:
  sessions-without-end:
    about: sessions with no end fact
    level: warn
    sql: SELECT session FROM sessions WHERE session NOT IN (SELECT session FROM facts_all WHERE kind = 'end')
minimums:
  events: 20
  exposure_hours: 0.5
  sessions: 2
eras:
  - id: one
    build: b1
  - id: two
    build: b2
---
# e2e app
"""


class Run:
    def __init__(self, out: Path, cwd: Path):
        self.out, self.cwd, self.n, self.results = out, cwd, 0, []

    def facts(self, *args, cwd=None, env=None, stdin=None):
        self.n += 1
        e = {**os.environ, "NO_COLOR": "1", **(env or {})}
        p = subprocess.run([str(FACTS), *args], cwd=cwd or self.cwd, capture_output=True, text=True, env=e, timeout=600,
                           input=stdin if stdin is not None else "")
        record = {"n": self.n, "args": list(args), "exit": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
        (self.out / "transcript.jsonl").open("a").write(json.dumps(record) + "\n")
        try:
            doc = json.loads(p.stdout) if p.stdout.strip() and args[:1] != ("guide",) and "--help" not in args else None
        except json.JSONDecodeError:
            doc = {"_unparsed": p.stdout}
        return p.returncode, doc, p.stderr

    def case(self, case_id, about, ok, detail=""):
        self.results.append({"case": case_id, "about": about, "pass": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {case_id:>4}  {about}" + (f"  ({detail})" if detail and not ok else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="artifact directory (default: new temp dir)")
    out = Path(ap.parse_args().out or tempfile.mkdtemp(prefix="facts-e2e-")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "transcript.jsonl").write_text("")
    work = Path(tempfile.mkdtemp(prefix="facts-e2e-work-"))
    app = work / "app"
    app.mkdir()
    Archive.objects = build_archive(work)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Archive)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    token_file = work / "token"
    r = Run(out, app)

    # 1: no contract anywhere
    code, doc, _ = r.facts("check", cwd=work)
    r.case("1", "no facts.md -> exit 2 naming facts init", code == 2 and any("facts init" in t for t in doc["error"]["try"]))
    # 2: invalid front matter
    (app / "facts.md").write_text("---\nfacts: 1\nname: x\nsource: [\n---\n")
    code, doc, _ = r.facts("sync")
    r.case("2", "invalid YAML front matter -> exit 2", code == 2 and "YAML" in doc["error"]["message"])
    (app / "facts.md").write_text("---\nfacts: 1\nname: x\nsource: {kind: ftp}\n---\n")
    code, doc, _ = r.facts("sync")
    r.case("2b", "unknown source kind -> exit 2 naming source.kind", code == 2 and "source.kind" in doc["error"]["message"])
    contract = CONTRACT.format(base=base, token_file=token_file)
    # 3: invalid field mapping
    (app / "facts.md").write_text(contract.replace("admin_kinds:", "fields:\n  kind: \"json_extract_string(json, \"\nadmin_kinds:"))
    token_file.write_text(TOKEN)
    code, doc, _ = r.facts("sync")
    r.case("3", "invalid field SQL -> exit 2 naming the field", code == 2 and "fields.kind" in doc["error"]["message"])
    (app / "facts.md").write_text(contract)
    # 13: nothing synced
    code, doc, _ = r.facts()
    r.case("13", "bare facts before sync succeeds and says sync", code == 0 and doc["data"]["synced"] is False and doc["next"][0] == "facts sync")
    code, doc, _ = r.facts("query", "SELECT 1")
    r.case("13b", "query before sync -> exit 3 with facts sync", code == 3 and doc["error"]["try"] == ["facts sync"])
    # 5: missing token file
    token_file.unlink()
    code, doc, err = r.facts("sync")
    r.case("5", "missing token file -> exit 4 naming it, token never printed", code == 4 and str(token_file) in doc["error"]["message"])
    # 6: rejected token
    token_file.write_text("wrong")
    code, doc, err = r.facts("sync")
    r.case("6", "401 -> exit 4 'rejected', no token echoed", code == 4 and "rejected" in doc["error"]["message"] and "wrong" not in json.dumps(doc) + err)
    token_file.write_text(TOKEN)
    # 12: busy
    (app / ".cache").mkdir(exist_ok=True)
    with open(app / ".cache" / ".sync.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        code, doc, _ = r.facts("sync")
    r.case("12", "sync while another sync holds the lock -> exit 6", code == 6)
    # 8: interrupted (limited) sync resumes
    code, doc, _ = r.facts("sync", "--limit", "1")
    first = doc and doc.get("data", {})
    r.case("8", "a partial sync ingests some and reports the rest", code == 0 and first.get("ingested") == 1 and first.get("remaining") == 5)
    # 7 + 9 + 10: the full sync retries the flaky object, records the corrupt one, counts bad lines
    code, doc, err = r.facts("sync")
    d = doc.get("data", {}) if doc else {}
    r.case("7", "a 503 is retried and the object ingests", "retrying" in err and not any("flaky" in f["key"] for f in d.get("failures", [])))
    r.case("9", "corrupt gzip -> exit 4, others ingested", code == 4 and d.get("failed") == 1 and d.get("ingested") == 4)
    code, doc, _ = r.facts()
    ids = {w["id"] for w in doc["data"]["warnings"]}
    r.case("10", "malformed JSON lines are counted and warned", "bad-lines" in ids)
    r.case("4", "a broken contract view is reported, not fatal", code == 0 and "view:broken_view" in ids)
    # 14-16: queries
    code, doc, _ = r.facts("query", "DELETE FROM facts_all")
    r.case("14", "mutating SQL refused (read-only)", code == 1 and "read-only" in doc["error"]["message"])
    code, doc, _ = r.facts("query", "SELECT nope FROM facts")
    r.case("15", "bad SQL -> exit 1 with facts schema hint", code == 1 and "facts schema" in doc["error"]["try"])
    code, doc, _ = r.facts("query", "SELECT count(*) FROM facts WHERE kind = 'death' AND data->>'$.target' = '1'")
    r.case("15b", "the JSON-arrow precedence trap is explained", code == 1 and "(data->>'$.x') = 'v'" in doc["error"]["message"])
    code, doc, _ = r.facts("query", "SELECT * FROM facts", "--limit", "5")
    r.case("16", "large result capped and marked truncated", code == 0 and doc["data"]["row_count"] == 5 and doc["data"]["truncated"] and doc["next"])
    code, doc, _ = r.facts("query", "SELECT count(*) AS n FROM human_deaths")
    r.case("4b", "working contract views still query", code == 0 and doc["data"]["rows"][0]["n"] > 0)
    # 17: exclusions
    code, doc, _ = r.facts("query", "SELECT (SELECT count(*) FROM facts WHERE session = 's5') AS admin_in_default, "
                                    "(SELECT count(*) FROM all_facts WHERE session = 's5') AS admin_in_all, "
                                    "(SELECT count(*) FROM facts WHERE who = 'agent') AS agent_in_default, "
                                    "(SELECT count(*) FROM all_facts WHERE who = 'agent') AS agent_in_all")
    row = doc["data"]["rows"][0]
    r.case("17", "admin sessions and agents excluded from facts, kept in all_facts",
           row["admin_in_default"] == 0 and row["admin_in_all"] > 0 and row["agent_in_default"] == 0 and row["agent_in_all"] > 0, str(row))
    # 18: who resolved through the actor
    code, doc, _ = r.facts("query", "SELECT DISTINCT who FROM facts WHERE kind = 'damage'")
    r.case("18", "a fact without who takes its actor's class", [x["who"] for x in doc["data"]["rows"]] == ["human"])
    code, doc, _ = r.facts("query", "SELECT data->>'$.marker' AS marker, target_who FROM facts WHERE session = 's2' "
                                    "AND kind = 'death' AND (data->>'$.marker') IS NOT NULL ORDER BY t")
    r.case("18b", "after a restart a reused actor number gets its new class (segments)",
           [(x["marker"], x["target_who"]) for x in doc["data"]["rows"]] == [("before", "bot"), ("after", "human")], json.dumps(doc)[:300])
    code, doc, _ = r.facts("query", "-", stdin="SELECT 41 + 1 AS answer")
    r.case("q-stdin", "SQL can come from stdin", code == 0 and doc["data"]["rows"] == [{"answer": 42}])
    (work / "q.sql").write_text("SELECT 'it''s' AS quoted")
    code, doc, _ = r.facts("query", "--file", str(work / "q.sql"))
    r.case("q-file", "SQL can come from --file (no shell quoting)", code == 0 and doc["data"]["rows"] == [{"quoted": "it's"}])
    code, _, _ = r.facts("--help")
    r.case("help", "--help works", code == 0)
    code, doc, _ = r.facts()
    ph = doc["data"]["play_hours"]
    r.case("play", "triage reports hours of play, with and without excluded sessions",
           ph["in_facts"].get("human", 0) > 0 and ph["including_admin_touched_sessions"]["human"] > ph["in_facts"]["human"], json.dumps(ph))
    code, doc, _ = r.facts("notes")
    r.case("notes", "notes prints the facts.md body and its SQL", code == 0 and "e2e app" in doc["data"]["notes"]
           and "exposure" in doc["data"]["sql"])
    code, doc, _ = r.facts("measures")
    r.case("measures", "measures lists each measure with its SQL", code == 0 and len(doc["data"]["measures"]) == 2
           and all(m["sql"] for m in doc["data"]["measures"]))
    # 19: typos
    code, doc, _ = r.facts("qurey", "SELECT 1")
    r.case("19", "command typo -> exit 1 suggesting the command", code == 1 and "facts query" in doc["error"]["try"])
    code, doc, _ = r.facts("query", "SELECT 1", "--limt", "3")
    r.case("19b", "flag typo -> exit 1 with the corrected command", code == 1 and any("--limit" in t for t in doc["error"]["try"]))
    # 20: unknown kind / era / session
    code, doc, _ = r.facts("schema", "deth")
    r.case("20", "unknown kind -> close match", code == 1 and "facts schema death" in doc["error"]["try"])
    code, doc, _ = r.facts("compare", "one", "tow")
    r.case("20b", "unknown era -> close match", code == 1 and any("two" in t for t in doc["error"]["try"]))
    code, doc, _ = r.facts("session", "zz")
    r.case("20c", "unknown session -> recent sessions listed", code == 1 and doc["error"]["try"])
    code, doc, _ = r.facts("session", "s1")
    r.case("20d", "session timeline hides bulky kinds and says how to see them",
           code == 0 and not any(e["kind"] == "shot" for e in doc["data"]["timeline"]) and doc["data"]["omitted_bulky_kinds"])
    # 21: compare
    code, doc, _ = r.facts("compare", "one", "two")
    res = {x["measure"]: x for x in doc["data"]["results"]}
    v = res["deaths-per-session-hour"]
    r.case("21", "clustered compare finds the real rise in deaths per hour", code == 0 and v["verdict"] == "up"
           and v["clustered"] and v["a"]["sessions"] == 2 and v["difference"]["low"] > 0
           and v["difference"]["of"].startswith("B − A"), json.dumps(v))
    d, sa = v["difference"], v["a"]
    r.case("21d", "the difference interval is not narrower than one side's own spread",
           (d["high"] - d["low"]) >= (sa["high"] - sa["low"]) * 0.9, json.dumps(d))
    r.case("21c", "an unclustered measure says its interval assumes independent events",
           res["deaths-flat"]["clustered"] is False and "independent" in res["deaths-flat"]["note"])
    code, doc, _ = r.facts("compare", "build:b2", "build:nothing")
    v = doc["data"]["results"][0]
    r.case("21b", "too little data -> 'not enough data'", code == 0 and v["verdict"] == "not enough data")
    # 22 + check: implausible time, failures, drift, custom checks
    code, doc, _ = r.facts("check")
    f = {x["id"]: x for x in doc["data"]["findings"]}
    r.case("22", "times in seconds fail the check", code == 5 and f["implausible-time"]["level"] == "fail")
    r.case("9b", "check fails while an object failed to ingest", f["sync-failures"]["level"] == "fail")
    r.case("era-cover", "builds no era covers are listed", f["builds-without-era"]["value"] == ["b3"], json.dumps(f["builds-without-era"]))
    r.case("check", "drift, conflicts and custom checks reported",
           f["undeclared-kinds"]["value"] == ["mystery"] and f["declared-never-seen"]["value"] == ["never"]
           and f["agent-conflicts"]["value"] == 1 and f["check:sessions-without-end"]["value"] >= 1, json.dumps(f)[:400])
    # 11: mapping change -> warn, then sync rebuilds without downloading
    gets = Archive.gets
    (app / "facts.md").write_text(contract.replace("admin_kinds: [admin]", "admin_kinds: [admin]\nfields:\n  who: lower(json_extract_string(json, '$.who'))"))
    code, doc, _ = r.facts()
    r.case("11", "changed mapping is warned", "mapping-changed" in {w["id"] for w in doc["data"]["warnings"]})
    code, doc, err = r.facts("sync")
    r.case("11b", "next sync rebuilds from local raw files", doc["data"]["rebuilt"] and Archive.gets - gets <= 1, f"gets {Archive.gets - gets}")
    (app / "facts.md").write_text((app / "facts.md").read_text().replace("sessionless: [perf]\n", ""))
    code, doc, _ = r.facts("check")
    f = {x["id"]: x for x in doc["data"]["findings"]}
    r.case("check-b", "missing build counted; reused ids flagged, but not across a restart in a later-sorting object",
           f["missing-build"]["value"] > 0 and f["actor-reused"]["value"] == 1, json.dumps([f["missing-build"], f["actor-reused"]])[:300])
    # 23: every stdout was one JSON document, no ANSI
    bad = []
    for line in (out / "transcript.jsonl").read_text().splitlines():
        rec = json.loads(line)
        if "--help" in rec["args"]:
            continue
        try:
            json.loads(rec["stdout"])
        except json.JSONDecodeError:
            bad.append(rec["n"])
        if "\x1b[" in rec["stdout"] + rec["stderr"]:
            bad.append(rec["n"])
    r.case("23", "stdout is always one JSON document, no ANSI", not bad, str(bad))
    fresh = work / "fresh"
    fresh.mkdir()
    code, doc, _ = r.facts("init", "--name", "demo", cwd=fresh)
    again, doc2, _ = r.facts("init", "--name", "demo", cwd=fresh)
    triage, doc3, _ = r.facts(cwd=fresh)
    r.case("init", "init writes a working facts.md once and never overwrites",
           code == 0 and again == 1 and triage == 0 and doc3["data"]["project"]["name"] == "demo")
    # 35: a dir source whose .jsonl grows (an append-only log) is re-ingested without duplicates
    grow = work / "grow"
    (grow / "log").mkdir(parents=True)
    (grow / "facts.md").write_text("---\nfacts: 1\nname: grow\nsource: {kind: dir, path: ./log}\ncache: .cache\n---\n")
    line = lambda i: json.dumps(fact("note", 1760000000000 + i, "s1", "b1", actor=1, who="human")) + "\n"
    (grow / "log" / "events.jsonl").write_text(line(1) + line(2))
    r.facts("sync", cwd=grow)
    with (grow / "log" / "events.jsonl").open("a") as f: f.write(line(3))
    code, doc, _ = r.facts("sync", cwd=grow)
    _, q, _ = r.facts("query", "SELECT count(*) AS n FROM facts_all", cwd=grow)
    r.case("35", "a grown dir .jsonl is re-ingested, replacing its rows",
           code == 0 and doc["data"]["ingested"] == 1 and q["data"]["rows"][0]["n"] == 3, json.dumps(q)[:200])
    code, doc, _ = r.facts("capabilities", cwd=work)
    r.case("caps", "capabilities works without a contract", code == 0 and doc["data"]["exit_codes"])

    server.shutdown()
    shutil.rmtree(work, ignore_errors=True)
    passed = sum(x["pass"] for x in r.results)
    summary = {"passed": passed, "failed": len(r.results) - passed, "cases": r.results,
               "facts": str(FACTS), "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (out / "results.json").write_text(json.dumps(summary, indent=1))
    print(f"\n{passed}/{len(r.results)} passed. Artifact: {out}")
    return 0 if passed == len(r.results) else 1


if __name__ == "__main__":
    sys.exit(main())
