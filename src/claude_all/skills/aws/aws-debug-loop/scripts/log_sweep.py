#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""All-groups CloudWatch log sweep -> sqlite, surfacing only the errors.

Fetches CloudWatch Logs for every log group whose name matches a filter, over a
time window, and loads EVERY event into a stdlib ``sqlite3`` database. During
ingest it flags events matching an error-keyword set (case-insensitive) and
prints a compact, deduplicated signature table -- group, a short snippet, the
sqlite rowid, and a count -- so the caller spends tokens only on real errors.

The caller then drills into any error by its rowid, pulling N lines of context
from the same stream::

    sqlite3 sweep.sqlite "SELECT ts_iso, message FROM logs \\
      WHERE log_stream = '<stream>' AND id BETWEEN <id>-5 AND <id>+5 ORDER BY id"

Rows are inserted ordered by (log_group, log_stream, ts), so the rowid is the
chronological position within a stream and ``id +/- N`` gives real context.

Stdlib only. Log fetching tries, in order: boto3 (if importable) -> the ``aws``
CLI -> the ``awslogs`` CLI. If none are available (or all fail), it warns and
exits non-zero.

Usage::

    log_sweep.py --profile myapp-dev --name-filter myapp-dev- --since 3h
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

DEFAULT_KEYWORDS: tuple[str, ...] = (
    "error",
    "exception",
    "traceback",
    "timeout",
    "fail",
    "denied",
    "throttl",
    "validationerror",
    "conflict",
)
# HTTP 4xx/5xx status codes as a standalone token, added to every keyword set.
_STATUS_RE = r"\b[45]\d\d\b"

_LEVELS: dict[str, int] = {
    "debug": 10,
    "info": 20,
    "warning": 30,
    "warn": 30,
    "error": 40,
    "critical": 50,
    "fatal": 50,
}
_UNIT_SECONDS: dict[str, int] = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_BACKENDS: tuple[str, ...] = ("boto3", "awscli", "awslogs")

_HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE)
_NUM_RE = re.compile(r"\d+")


@dataclass(slots=True)
class LogEvent:
    """One CloudWatch log event, normalized across backends."""

    log_group: str
    log_stream: str
    ts: int | None  # epoch milliseconds (None when the backend can't supply it)
    message: str


# ---------------------- time parsing ----------------------


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def parse_time(value: str, *, now_ms: int) -> int:
    """Parse a relative (``3h``/``30m``/``2d``/``90s``) or ISO-8601 time to epoch ms."""
    text = value.strip().lower()
    if text in {"now", ""}:
        return now_ms
    rel = re.fullmatch(r"(\d+)\s*([smhd])(?:\s*ago)?", text)
    if rel:
        return now_ms - int(rel.group(1)) * _UNIT_SECONDS[rel.group(2)] * 1000
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(
            f"error: cannot parse time {value!r} (use e.g. '3h', '30m', or ISO-8601)"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts / 1000, tz=UTC).isoformat()


# ---------------------- group selection ----------------------


def _select_groups(names: list[str], args: argparse.Namespace) -> list[str]:
    excludes = [x for x in args.exclude.split(",") if x]
    chosen = [
        n
        for n in names
        if args.name_filter in n and not any(x in n for x in excludes)
    ]
    return sorted(set(chosen))


# ---------------------- backends ----------------------


def _available(backend: str) -> bool:
    if backend == "boto3":
        return importlib.util.find_spec("boto3") is not None
    tool = "aws" if backend == "awscli" else "awslogs"
    return shutil.which(tool) is not None


def _aws_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    env["AWS_PROFILE"] = args.profile
    env["AWS_REGION"] = args.region
    env["AWS_DEFAULT_REGION"] = args.region
    return env


def _fetch_boto3(args: argparse.Namespace, since_ms: int, until_ms: int) -> list[LogEvent]:
    import boto3  # optional dependency, imported only when this backend runs

    client = boto3.Session(profile_name=args.profile, region_name=args.region).client("logs")

    names: list[str] = []
    for page in client.get_paginator("describe_log_groups").paginate():
        names += [g.get("logGroupName", "") for g in page.get("logGroups", [])]

    events: list[LogEvent] = []
    for name in _select_groups(names, args):
        count = 0
        stop = False
        pages = client.get_paginator("filter_log_events").paginate(
            logGroupName=name, startTime=since_ms, endTime=until_ms
        )
        for page in pages:
            for e in page.get("events", []):
                stream = e.get("logStreamName", "")
                if args.stream_filter and args.stream_filter not in stream:
                    continue
                events.append(LogEvent(name, stream, e.get("timestamp"), e.get("message", "")))
                count += 1
                if args.max_events and count >= args.max_events:
                    stop = True
                    break
            if stop:
                break
    return events


def _aws_json(args: argparse.Namespace, *cmd: str) -> dict:
    base = ["aws", "--profile", args.profile, "--region", args.region, "--output", "json", *cmd]
    proc = subprocess.run(base, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout or "{}")


def _fetch_awscli(args: argparse.Namespace, since_ms: int, until_ms: int) -> list[LogEvent]:
    names: list[str] = []
    token: str | None = None
    while True:
        cmd = ["logs", "describe-log-groups"]
        if token:
            cmd += ["--next-token", token]
        data = _aws_json(args, *cmd)
        names += [g.get("logGroupName", "") for g in data.get("logGroups", [])]
        token = data.get("nextToken")
        if not token:
            break

    events: list[LogEvent] = []
    for name in _select_groups(names, args):
        token = None
        count = 0
        while True:
            cmd = [
                "logs",
                "filter-log-events",
                "--log-group-name",
                name,
                "--start-time",
                str(since_ms),
                "--end-time",
                str(until_ms),
            ]
            if token:
                cmd += ["--next-token", token]
            data = _aws_json(args, *cmd)
            for e in data.get("events", []):
                stream = e.get("logStreamName", "")
                if args.stream_filter and args.stream_filter not in stream:
                    continue
                events.append(LogEvent(name, stream, e.get("timestamp"), e.get("message", "")))
                count += 1
            token = data.get("nextToken")
            if not token or (args.max_events and count >= args.max_events):
                break
    return events


def _fetch_awslogs(args: argparse.Namespace, _since_ms: int, _until_ms: int) -> list[LogEvent]:
    # The awslogs CLI takes the window as strings (args.since/args.until), so the
    # epoch-ms args are unused here; kept for a uniform backend signature.
    env = _aws_env(args)
    groups_out = subprocess.run(
        ["awslogs", "groups"], capture_output=True, text=True, check=True, env=env
    ).stdout
    events: list[LogEvent] = []
    for name in _select_groups(groups_out.split(), args):
        cmd = ["awslogs", "get", name, "ALL", f"--start={args.since}", "--no-color"]
        if args.until.lower() != "now":
            cmd.append(f"--end={args.until}")
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env).stdout
        count = 0
        for line in out.splitlines():
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            _group, stream, message = parts
            if args.stream_filter and args.stream_filter not in stream:
                continue
            events.append(LogEvent(name, stream, None, message))
            count += 1
            if args.max_events and count >= args.max_events:
                break
    return events


def fetch_all(args: argparse.Namespace, since_ms: int, until_ms: int) -> tuple[str, list[LogEvent]]:
    """Fetch via the first working backend; on total failure, warn and exit."""
    order = list(_BACKENDS) if args.backend == "auto" else [args.backend]
    fns = {"boto3": _fetch_boto3, "awscli": _fetch_awscli, "awslogs": _fetch_awslogs}
    problems: list[str] = []
    for backend in order:
        if not _available(backend):
            problems.append(f"{backend}: not installed / importable")
            continue
        try:
            return backend, fns[backend](args, since_ms, until_ms)
        except Exception as exc:  # any backend runtime failure -> record and try the next
            problems.append(f"{backend}: {type(exc).__name__}: {exc}")
    raise SystemExit(
        "warning: could not fetch logs from any backend:\n  " + "\n  ".join(problems)
    )


# ---------------------- parsing + classification ----------------------


def _as_str(value: object) -> str | None:
    return None if value is None else str(value)


def _parse_json(message: str) -> tuple[bool, str | None, str | None, str | None]:
    """Return (is_json, level, event, fields_json) for a structlog-style line."""
    text = message.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return False, None, None, None
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False, None, None, None
    if not isinstance(obj, dict):
        return False, None, None, None
    level = obj.get("level") or obj.get("levelname") or obj.get("severity")
    event = obj.get("event") or obj.get("msg") or obj.get("message")
    return True, _as_str(level), _as_str(event), json.dumps(obj, ensure_ascii=False)


def build_hit_re(keywords: list[str]) -> re.Pattern[str]:
    parts = [re.escape(k) for k in keywords] + [_STATUS_RE]
    return re.compile("|".join(parts), re.IGNORECASE)


def classify(
    pattern: re.Pattern[str],
    message: str,
    is_json: bool,
    level: str | None,
    level_floor: int,
) -> str | None:
    """Return the matched keyword/level if this event is an error hit, else None."""
    match = pattern.search(message)
    if match:
        return match.group(0)
    if level_floor and is_json and level and _LEVELS.get(level.lower(), 0) >= level_floor:
        return level.upper()
    return None


def _mask(text: str) -> str:
    collapsed = " ".join(text.replace("\n", " ").split())
    return _NUM_RE.sub("<n>", _HEX_RE.sub("<hex>", collapsed))


def signature_of(
    is_json: bool, level: str | None, event: str | None, message: str, matched: str
) -> str:
    if is_json and event:
        return f"{(level or '?').upper()}:{_mask(event)[:80]}"
    return f"{matched.lower()}:{_mask(message)[:80]}"


def snippet_of(message: str, matched: str, width: int) -> str:
    line = " ".join(message.split())
    idx = max(line.lower().find(matched.lower()), 0)
    half = max(0, width // 2)
    start = max(0, idx - half)
    end = min(len(line), idx + len(matched) + half)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(line) else ""
    return f"{prefix}{line[start:end]}{suffix}"


# ---------------------- ingest + report ----------------------


def ingest(
    events: list[LogEvent],
    args: argparse.Namespace,
    pattern: re.Pattern[str],
    level_floor: int,
) -> list[dict]:
    """Load every event into sqlite (ordered per stream); return the error hits."""
    con = sqlite3.connect(args.db)
    con.execute("DROP TABLE IF EXISTS logs")
    con.execute(
        "CREATE TABLE logs ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " log_group TEXT, log_stream TEXT, ts INTEGER, ts_iso TEXT,"
        " level TEXT, event TEXT, message TEXT, is_json INTEGER, fields TEXT)"
    )
    events.sort(key=lambda e: (e.log_group, e.log_stream, e.ts if e.ts is not None else 0))
    hits: list[dict] = []
    cur = con.cursor()
    for e in events:
        is_json, level, event, fields = _parse_json(e.message)
        cur.execute(
            "INSERT INTO logs"
            " (log_group, log_stream, ts, ts_iso, level, event, message, is_json, fields)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e.log_group, e.log_stream, e.ts, _iso(e.ts), level, event, e.message, int(is_json), fields),
        )
        matched = classify(pattern, e.message, is_json, level, level_floor)
        if matched:
            hits.append(
                {
                    "id": cur.lastrowid,
                    "group": e.log_group,
                    "stream": e.log_stream,
                    "sig": signature_of(is_json, level, event, e.message, matched),
                    "snippet": snippet_of(e.message, matched, args.snippet_chars),
                    "ts": e.ts,
                }
            )
    con.execute("CREATE INDEX idx_stream ON logs (log_stream, id)")
    con.commit()
    con.close()
    return hits


def _dedupe(hits: list[dict]) -> list[dict]:
    by_sig: dict[str, dict] = {}
    for h in hits:
        agg = by_sig.get(h["sig"])
        if agg is None:
            by_sig[h["sig"]] = {**h, "count": 1}
            continue
        agg["count"] += 1
        # Keep the earliest occurrence as the representative example.
        if h["ts"] is not None and (agg["ts"] is None or h["ts"] < agg["ts"]):
            agg.update(id=h["id"], group=h["group"], stream=h["stream"], snippet=h["snippet"], ts=h["ts"])
    return sorted(by_sig.values(), key=lambda r: r["count"], reverse=True)


def report(used_backend: str, n_groups: int, n_events: int, hits: list[dict], args: argparse.Namespace) -> None:
    print(
        f"sweep -> {args.db} | backend={used_backend} | "
        f"groups={n_groups} events={n_events} | window={args.since}..{args.until}"
    )
    print(
        "schema: id, log_group, log_stream, ts, ts_iso, level, event, message, is_json, fields"
    )
    if not hits:
        print("CLEAN -- 0 error signatures.")
        return
    rows = _dedupe(hits)
    print(f"HITS -- {len(rows)} signatures / {len(hits)} occurrences\n")
    print(f"{'count':>5}  {'group':<30}  {'id':>8}  snippet")
    for r in rows:
        print(f"{r['count']:>5}  {r['group'][-30:]:<30}  {r['id']:>8}  {r['snippet']}")
    example = rows[0]
    print(f"\nContext (+/-{args.context} lines in the same stream), e.g. the top signature:")
    print(
        f"  sqlite3 {args.db} \"SELECT ts_iso, level, message FROM logs"
        f" WHERE log_stream = '{example['stream']}'"
        f" AND id BETWEEN {example['id']} - {args.context} AND {example['id']} + {args.context}"
        ' ORDER BY id"'
    )


# ---------------------- cli ----------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="All-groups CloudWatch log sweep into sqlite, surfacing only the errors.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--profile", required=True, help="AWS profile")
    p.add_argument(
        "--name-filter",
        required=True,
        help="only sweep log groups whose name contains this substring (e.g. myapp-dev-)",
    )
    p.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    p.add_argument("--since", default="3h", help="window start: 3h/30m/2d/90s or ISO-8601 (default 3h)")
    p.add_argument("--until", default="now", help="window end: 'now' or ISO-8601 (default now)")
    p.add_argument("--db", default="./sweep.sqlite", help="output sqlite path (default ./sweep.sqlite)")
    p.add_argument("--backend", choices=("auto", *_BACKENDS), default="auto")
    p.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="comma-separated error keywords, case-insensitive (4xx/5xx always added)",
    )
    p.add_argument("--level", default=None, help="also flag JSON logs at/above this level (e.g. WARNING)")
    p.add_argument("--max-events", type=int, default=0, help="per-group event cap (0 = no cap)")
    p.add_argument("--snippet-chars", type=int, default=120, help="chars of context around each match")
    p.add_argument("--stream-filter", default="", help="only keep streams whose name contains this")
    p.add_argument("--exclude", default="", help="comma-separated group-name substrings to skip")
    p.add_argument("--context", type=int, default=5, help="+/- lines for the context query hint")
    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    now_ms = _now_ms()
    since_ms = parse_time(args.since, now_ms=now_ms)
    until_ms = parse_time(args.until, now_ms=now_ms)
    level_floor = _LEVELS.get(args.level.lower(), 0) if args.level else 0
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    pattern = build_hit_re(keywords)

    used_backend, events = fetch_all(args, since_ms, until_ms)
    n_groups = len({e.log_group for e in events})
    hits = ingest(events, args, pattern, level_floor)
    report(used_backend, n_groups, len(events), hits, args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
