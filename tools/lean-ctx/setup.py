#!/usr/bin/env python3
"""Merge desired lean-ctx config values into the existing config file.

Run after `lean-ctx config init`. Reads the current config with stdlib
tomllib, deep-merges our values (ours win on conflict), and writes it
back. Handles scalar and array types — no third-party deps required.
"""

import sys
import tomllib
from pathlib import Path

CONFIG = Path.home() / ".config" / "lean-ctx" / "config.toml"

DESIRED: dict = {
    # ── High-level knobs ────────────────────────────────────────────────
    "compression_level": "standard",
    "profile": "coder",
    "shell_activation": "agents-only",
    "memory_profile": "performance",
    "bm25_max_cache_mb": 256,
    "max_ram_percent": 8,
    "memory_cleanup": "shared",
    "checkpoint_interval": 10,
    "rules_scope": "both",
    "tee_mode": "failures",
    "slow_command_threshold_ms": 3000,
    # ── Hook redirect exclusions ─────────────────────────────────────────
    "redirect_exclude": [
        ".claude/**",
        "CLAUDE.md",
        "*.toml",
        ".pre-commit-config.yaml",
    ],
    # ── Memory subsystem ────────────────────────────────────────────────
    "memory": {
        "knowledge": {"max_facts": 400, "max_patterns": 100},
        "episodic": {"max_episodes": 1000},
        "lifecycle": {"stale_days": 60, "decay_rate": 0.005, "similarity_threshold": 0.85},
    },
    # ── Tool result archive ──────────────────────────────────────────────
    "archive": {
        "enabled": True,
        "threshold_chars": 4096,
        "max_age_hours": 72,
        "max_disk_mb": 1000,
    },
    # ── Autonomy (background optimizations) ─────────────────────────────
    "autonomy": {
        "enabled": True,
        "auto_preload": True,
        "auto_dedup": True,
        "auto_related": True,
        "auto_consolidate": True,
        "silent_preload": True,
        "dedup_threshold": 8,
        "consolidate_every_calls": 25,
        "consolidate_cooldown_secs": 120,
    },
    # ── Secret detection ─────────────────────────────────────────────────
    "secret_detection": {
        "enabled": True,
        "redact": True,
        "custom_patterns": [
            "AKIA[0-9A-Z]{16}",
            "sk-[a-zA-Z0-9]{48}",
        ],
    },
    # ── Cloud telemetry — off ────────────────────────────────────────────
    "cloud": {"contribute_enabled": False},
}


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def toml_val(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, list):
        items = "\n".join(f'    "{x}",' if isinstance(x, str) else f"    {x}," for x in v)
        return f"[\n{items}\n]"
    raise TypeError(f"Unsupported TOML type: {type(v)}")


def serialise(data: dict, prefix: str = "") -> list[str]:
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {toml_val(v)}")
    for k, v in tables.items():
        header = f"{prefix}.{k}" if prefix else k
        # skip empty intermediate section headers (e.g. [memory] when it only has subtables)
        if any(not isinstance(sv, dict) for sv in v.values()):
            lines.append(f"\n[{header}]")
        lines.extend(serialise(v, header))
    return lines


def main() -> None:
    if not CONFIG.exists():
        sys.exit(f"lean-ctx config not found at {CONFIG} — run `lean-ctx config init` first")
    with open(CONFIG, "rb") as f:
        existing = tomllib.load(f)
    merged = deep_merge(existing, DESIRED)
    CONFIG.write_text("\n".join(serialise(merged)) + "\n")
    print(f"lean-ctx config merged → {CONFIG}")


if __name__ == "__main__":
    main()
