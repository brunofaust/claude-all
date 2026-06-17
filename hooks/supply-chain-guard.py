#!/usr/bin/env python3
"""PreToolUse hook — flag supply-chain risks in package-install commands.

Fires on the `Bash` tool. When the command installs packages
(`npm/pnpm/yarn/bun install|add|ci`, `pip install`, `uv add`, `uv pip install`,
`uv sync`, `poetry add`, `poetry install`, `pipx install`), it emits a
NON-BLOCKING reminder (exit 0 + JSON `additionalContext`, so it is NOT rendered as
a hook error) covering the applicable risks and the safer invocation.

STATIC checks (no network, instant):
- **git/URL sources** (`git+https://`, `github:owner/repo`, `git://`) bypass
  registry review and run arbitrary code — strongly avoid.
- **lifecycle scripts** run arbitrary code at install time — pass
  `--ignore-scripts` on npm/pnpm/yarn/bun and run the build deliberately.
- **lockfile drift** — a bare `npm install` with a lockfile present mutates it;
  use the frozen/`ci` variant for a reproducible install.
- **alternate Python indexes** — `--index-url`/`--extra-index-url` can shadow
  public names (dependency confusion); `--trusted-host` disables TLS verification.

COOLDOWN check (queries the registry; the actual Shai-Hulud-style defense):
- For every package being installed — named on the command line OR resolved from
  the lockfile for `uv sync` / `poetry install` / `npm ci` / `pip -r` — it looks up
  the release date and ALERTS if the version was published within the cooldown
  window (default 7 days; most malicious releases are caught within days). Publish
  dates of pinned versions are cached on disk (they're immutable), and the whole
  check runs under a time budget with a tool-call-safe per-request timeout, so it
  stays fast and FAILS OPEN — a registry it can't reach never blocks the install.

Covers npm/pnpm/yarn/bun and pip/pipx/uv/poetry. Env:
  CC_SUPPLY_CHAIN_OK=1            silence the whole hook
  CC_SUPPLY_CHAIN_NO_NETWORK=1   skip the cooldown lookup (keep the static checks)
  CC_SUPPLY_CHAIN_COOLDOWN_DAYS  cooldown window in days (default 7)
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["analyze", "classify", "cooldown_findings", "main"]

# ── static-check patterns ────────────────────────────────────────────────────
JS_INSTALL_RE = re.compile(r"\b(npm|pnpm|yarn|bun)\s+(install|i|add|ci)\b")
PY_INSTALL_RE = re.compile(
    r"\b(pip3?|pipx)\s+install\b|\buv\s+(pip\s+install|add)\b|\bpoetry\s+add\b"
)
GIT_URL_RE = re.compile(r"git\+(?:https?|ssh)://|(?<![\w-])github:[\w.-]+/[\w.-]+|(?<![\w/])git://")
PY_INDEX_RE = re.compile(r"--(?:extra-)?index-url\b")
BARE_INSTALL_RE = re.compile(r"\b(npm|pnpm|yarn|bun)\s+(install|i)\b(?!\s+[\w@./-])")

LOCKFILES: dict[str, tuple[str, str]] = {
    "package-lock.json": ("npm", "npm ci"),
    "pnpm-lock.yaml": ("pnpm", "pnpm install --frozen-lockfile"),
    "yarn.lock": ("yarn", "yarn install --immutable"),
    "bun.lockb": ("bun", "bun install --frozen-lockfile"),
}

# ── cooldown-check tunables ──────────────────────────────────────────────────
COOLDOWN_DAYS = int(os.environ.get("CC_SUPPLY_CHAIN_COOLDOWN_DAYS", "7"))
MAX_PKGS = 60  # cap registry lookups per command (lockfiles can be huge)
WORKERS = 8
BUDGET_SECONDS = 6.0  # overall wall-clock budget for the lookups
REQ_TIMEOUT = 3.0  # per-request timeout (keeps stray threads short-lived)
USER_AGENT = "claude-all-supply-chain-guard"
OPERATORS = frozenset({"&&", "||", ";", "|", ">", ">>", "<", "&"})


def nudge(message: str) -> int:
    """Emit a non-error reminder into Claude's context, then allow the tool."""
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}},
        sys.stdout,
    )
    return 0


# ── static checks ────────────────────────────────────────────────────────────
def analyze(command: str, cwd: Path) -> list[str]:
    """Static (no-network) supply-chain findings for one Bash command."""
    js = JS_INSTALL_RE.search(command)
    py = PY_INSTALL_RE.search(command)
    if not (js or py):
        return []

    findings: list[str] = []
    if GIT_URL_RE.search(command):
        findings.append(
            "⛔ installing from a git/URL source bypasses registry review and runs that repo's "
            "code — avoid it; prefer a published, pinned package."
        )
    if js and js.group(2) != "ci" and "--ignore-scripts" not in command:
        findings.append(
            "add `--ignore-scripts` — install/postinstall lifecycle hooks run arbitrary code; "
            "install with scripts off, then run the build step deliberately."
        )
    if py and PY_INDEX_RE.search(command):
        findings.append(
            "a custom package index (`--index-url`/`--extra-index-url`) can shadow public names "
            "(dependency confusion) — pin exact versions + hashes and prefer one trusted index."
        )
    if py and "--trusted-host" in command:
        findings.append(
            "`--trusted-host` disables TLS/certificate verification for that host — avoid it; "
            "fix the index's certificate instead of trusting it blindly."
        )
    bare = BARE_INSTALL_RE.search(command)
    if bare:
        for lock_name, (mgr, frozen) in LOCKFILES.items():
            if bare.group(1) == mgr and (cwd / lock_name).is_file():
                findings.append(
                    f"a lockfile is present — use `{frozen}` for a reproducible install instead of "
                    "a bare `install` (which can mutate the lockfile / resolve unpinned versions)."
                )
    if findings or py or (js and js.group(2) in {"add", "install", "i"}):
        findings.append(
            "verify the package's provenance and pin the version, and commit the lockfile."
        )
    return findings


# ── install classification (for the cooldown lookup) ─────────────────────────
def _args_until_operator(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for tok in tokens:
        if tok in OPERATORS:
            break
        out.append(tok)
    return out


def _requirement_file(args: list[str]) -> str | None:
    for i, a in enumerate(args):
        if a in {"-r", "--requirement"} and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--requirement="):
            return a.split("=", 1)[1]
    return None


def classify(command: str) -> tuple[str, str, list[str], str | None]:
    """Return (ecosystem, mode, named_pkgs, requirement_file).

    ecosystem ∈ {"npm","pypi",""}; mode ∈ {"named","lock",""}. For `lock` mode the
    packages come from a lockfile (named_pkgs empty); requirement_file is set when a
    `pip -r <file>` was used.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    n = len(tokens)
    for i, tok in enumerate(tokens):
        base = tok.rsplit("/", 1)[-1]
        nxt = tokens[i + 1] if i + 1 < n else ""
        after = tokens[i + 1 :]
        if base in {"npm", "pnpm", "yarn", "bun"} and nxt in {"install", "i", "add", "ci"}:
            if nxt == "ci":
                return ("npm", "lock", [], None)
            pkgs = [a for a in _args_until_operator(after[1:]) if not a.startswith("-")]
            return ("npm", "named", pkgs, None) if pkgs else ("npm", "lock", [], None)
        if base in {"pip", "pip3", "pipx"} and nxt == "install":
            args = _args_until_operator(after[1:])
            req = _requirement_file(args)
            if req:
                return ("pypi", "lock", [], req)
            pkgs = [a for a in args if not a.startswith("-")]
            return ("pypi", "named", pkgs, None) if pkgs else ("", "", [], None)
        if base == "uv" and nxt == "add":
            pkgs = [a for a in _args_until_operator(after[1:]) if not a.startswith("-")]
            if pkgs:
                return ("pypi", "named", pkgs, None)
        if base == "uv" and nxt == "sync":
            return ("pypi", "lock", [], None)
        if base == "uv" and nxt == "pip" and (tokens[i + 2] if i + 2 < n else "") == "install":
            args = _args_until_operator(after[2:])
            req = _requirement_file(args)
            if req:
                return ("pypi", "lock", [], req)
            pkgs = [a for a in args if not a.startswith("-")]
            if pkgs:
                return ("pypi", "named", pkgs, None)
        if base == "poetry" and nxt == "add":
            pkgs = [a for a in _args_until_operator(after[1:]) if not a.startswith("-")]
            if pkgs:
                return ("pypi", "named", pkgs, None)
        if base == "poetry" and nxt == "install":
            return ("pypi", "lock", [], None)
    return ("", "", [], None)


# ── package spec + lockfile parsing ──────────────────────────────────────────
def _split_npm(token: str) -> tuple[str, str | None]:
    if token.startswith("@"):
        at = token.find("@", 1)
        return (token, None) if at == -1 else (token[:at], token[at + 1 :] or None)
    name, _, ver = token.partition("@")
    return (name, ver or None)


def _split_py(token: str) -> tuple[str, str | None]:
    token = re.sub(r"\[.*?\]", "", token)
    pinned = re.match(r"^([A-Za-z0-9._-]+)==([^\s,;]+)", token)
    if pinned:
        return (pinned.group(1), pinned.group(2))
    name = re.match(r"^([A-Za-z0-9._-]+)", token)
    return (name.group(1), None) if name else (token, None)


def _parse_named(eco: str, pkgs: list[str]) -> list[tuple[str, str | None]]:
    split = _split_npm if eco == "npm" else _split_py
    return [split(p) for p in pkgs if p and not p.startswith("-")]


def _parse_requirements(path: Path) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        out.append(_split_py(line))
    return out


def _parse_toml_lock(path: Path) -> list[tuple[str, str | None]]:
    try:
        import tomllib
    except ModuleNotFoundError:
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[tuple[str, str | None]] = []
    for pkg in data.get("package") or []:
        name, ver = pkg.get("name"), pkg.get("version")
        if name and ver:
            out.append((name, ver))
    return out


def _parse_npm_lock(path: Path) -> list[tuple[str, str | None]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[tuple[str, str | None]] = []
    for key, meta in (data.get("packages") or {}).items():
        if not key:
            continue
        name = key.rsplit("node_modules/", 1)[-1]
        ver = (meta or {}).get("version")
        if name and ver:
            out.append((name, ver))
    for name, meta in (data.get("dependencies") or {}).items():
        ver = (meta or {}).get("version")
        if name and ver:
            out.append((name, ver))
    return out


def _lock_targets(eco: str, req: str | None, cwd: Path) -> list[tuple[str, str | None]]:
    if req:
        path = cwd / req
        return _parse_requirements(path) if path.is_file() else []
    if eco == "npm":
        path = cwd / "package-lock.json"
        return _parse_npm_lock(path) if path.is_file() else []
    for name in ("uv.lock", "poetry.lock"):
        path = cwd / name
        if path.is_file():
            return _parse_toml_lock(path)
    return []


# ── registry lookups + cooldown ──────────────────────────────────────────────
def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _npm_published(name: str, version: str | None) -> str | None:
    data = _http_json(f"https://registry.npmjs.org/{name.replace('/', '%2F')}")
    times = data.get("time") or {}
    if version is None:
        version = (data.get("dist-tags") or {}).get("latest")
    return times.get(version) if version else None


def _pypi_published(name: str, version: str | None) -> str | None:
    base = f"https://pypi.org/pypi/{name}"
    data = _http_json(f"{base}/{version}/json" if version else f"{base}/json")
    stamps = [u.get("upload_time_iso_8601") for u in (data.get("urls") or [])]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else None


def _published(eco: str, name: str, version: str | None) -> str | None:
    try:
        return _npm_published(name, version) if eco == "npm" else _pypi_published(name, version)
    except Exception:
        return None  # fail open — never block an install because a registry was unreachable


def _age_days(iso: str) -> int | None:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max(0, (datetime.now(UTC) - dt).days)


def _cache_path() -> Path:
    base = os.environ.get("CLAUDE_CACHE_DIR")
    root = Path(base) if base else Path.home() / ".claude" / "cache"
    directory = root / "supply-chain"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory = Path(tempfile.gettempdir())
    return directory / "publish-dates.json"


def _load_cache(path: Path) -> dict[str, str]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in loaded.items()} if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def cooldown_findings(
    eco: str, mode: str, named: list[str], req: str | None, cwd: Path, days: int
) -> list[str]:
    """Alert on packages whose release date is within the cooldown window."""
    targets = _parse_named(eco, named) if mode == "named" else _lock_targets(eco, req, cwd)
    seen: set[tuple[str, str | None]] = set()
    uniq: list[tuple[str, str | None]] = []
    for name, ver in targets:
        if name and (name, ver) not in seen:
            seen.add((name, ver))
            uniq.append((name, ver))
    uniq = uniq[:MAX_PKGS]
    if not uniq:
        return []

    cache_path = _cache_path()
    cache = _load_cache(cache_path)
    resolved: dict[tuple[str, str | None], str] = {}
    misses: list[tuple[str, str | None]] = []
    for name, ver in uniq:
        key = f"{eco}:{name}:{ver}"
        if ver is not None and key in cache:
            resolved[(name, ver)] = cache[key]
        else:
            misses.append((name, ver))

    if misses:
        pool = ThreadPoolExecutor(max_workers=WORKERS)
        futures = {pool.submit(_published, eco, name, ver): (name, ver) for name, ver in misses}
        try:
            for fut in as_completed(futures, timeout=BUDGET_SECONDS):
                name, ver = futures[fut]
                try:
                    iso = fut.result()
                except Exception:
                    iso = None
                if iso:
                    resolved[(name, ver)] = iso
        except TimeoutError:
            pass  # budget hit — report what resolved in time
        pool.shutdown(wait=False, cancel_futures=True)
        updated = False
        for (name, ver), iso in resolved.items():
            key = f"{eco}:{name}:{ver}"
            if ver is not None and cache.get(key) != iso:
                cache[key] = iso
                updated = True
        if updated:
            with contextlib.suppress(OSError):
                cache_path.write_text(json.dumps(cache), encoding="utf-8")

    findings: list[str] = []
    for name, ver in uniq:
        iso = resolved.get((name, ver))
        if not iso:
            continue
        age = _age_days(iso)
        if age is not None and age < days:
            findings.append(
                f"⛔ {name} {ver or '(latest)'} was published {age} day(s) ago (< {days}-day "
                "cooldown) — too new to trust; wait out the cooldown or pin a known-good "
                "older version."
            )
    return findings


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if data.get("tool_name") != "Bash" or os.environ.get("CC_SUPPLY_CHAIN_OK"):
        return 0

    command: str = data.get("tool_input", {}).get("command", "")
    if not command:
        return 0

    cwd = Path(data.get("cwd") or os.getcwd())
    cooldown: list[str] = []
    if not os.environ.get("CC_SUPPLY_CHAIN_NO_NETWORK"):
        eco, mode, named, req = classify(command)
        if eco:
            cooldown = cooldown_findings(eco, mode, named, req, cwd, COOLDOWN_DAYS)

    findings = cooldown + analyze(command, cwd)
    if not findings:
        return 0

    body = "\n".join(f"  - {f}" for f in findings)
    return nudge(
        "[supply-chain-guard] This command installs packages. Supply-chain checks:\n"
        f"{body}\n"
        "Proceed only if the change is intended. Set CC_SUPPLY_CHAIN_OK=1 to silence this reminder."
    )


if __name__ == "__main__":
    sys.exit(main())
