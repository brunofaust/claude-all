#!/usr/bin/env python3
"""Checker: no aws_lambda_function may set an env var AWS reserves for the runtime.

Lambda rejects such a configuration (InvalidParameterValueException), so the next
`terraform apply` fails. `terraform validate` and `fmt` both pass on it. Owns the
stdlib-only HCL text helpers shared by the sibling Terraform checkers.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "RESERVED_ENV_NAMES",
    "EnvEntry",
    "EnvMap",
    "ResourceBlock",
    "check_file",
    "collect_files",
    "lambda_env_maps",
    "line_of",
    "main",
    "resource_blocks",
    "strip_comments",
]

# https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html
RESERVED_ENV_NAMES: frozenset[str] = frozenset(
    {
        "AWS_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_DEFAULT_REGION",
        "AWS_EXECUTION_ENV",
        "AWS_LAMBDA_FUNCTION_MEMORY_SIZE",
        "AWS_LAMBDA_FUNCTION_NAME",
        "AWS_LAMBDA_FUNCTION_VERSION",
        "AWS_LAMBDA_INITIALIZATION_TYPE",
        "AWS_LAMBDA_LOG_GROUP_NAME",
        "AWS_LAMBDA_LOG_STREAM_NAME",
        "AWS_LAMBDA_RUNTIME_API",
        "AWS_REGION",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "LAMBDA_RUNTIME_DIR",
        "LAMBDA_TASK_ROOT",
        "_HANDLER",
        "_X_AMZN_TRACE_ID",
    }
)
RESOURCE_RE = re.compile(r'\bresource\s+"(?P<type>[^"]+)"\s+"(?P<name>[^"]+)"\s*\{')
ENV_BLOCK_RE = re.compile(r"\benvironment\s*\{")
VARIABLES_RE = re.compile(r"\bvariables\s*=\s*")
ENTRY_RE = re.compile(r'\s*"?(?P<key>[A-Za-z_][A-Za-z0-9_]*)"?\s*[=:]\s*(?P<value>.*\S)', re.S)
CLOSERS = {"{": "}", "(": ")", "[": "]"}


class ResourceBlock(NamedTuple):
    """One `resource` block: its type, name, line and [start, end) body offsets."""

    rtype: str
    name: str
    line: int
    start: int
    end: int


class EnvEntry(NamedTuple):
    """One env var: name, literal value (None when computed), raw expression, line."""

    name: str
    literal: str | None
    expr: str
    line: int


class EnvMap(NamedTuple):
    """A Lambda's env: literal entries plus opaque (uncountable) expressions."""

    resource: str
    line: int
    entries: list[EnvEntry]
    opaque: list[str]


def string_end(text: str, i: int) -> int:
    """Return the index after the string literal opening at text[i]."""
    i += 1
    while i < len(text):
        char = text[i]
        if char == "\\":
            i += 2
            continue
        if char == '"':
            return i + 1
        if text.startswith("${", i):
            i = group_end(text, i + 1)
            continue
        i += 1
    return i


def group_end(text: str, i: int) -> int:
    """Return the index after the bracket group opening at text[i], skipping strings."""
    stack = [CLOSERS[text[i]]]
    i += 1
    while i < len(text) and stack:
        char = text[i]
        if char == '"':
            i = string_end(text, i)
            continue
        if char in CLOSERS:
            stack.append(CLOSERS[char])
        elif char == stack[-1]:
            stack.pop()
        i += 1
    return i


def strip_comments(text: str) -> str:
    """Blank `#`, `//` and `/* */` comments in text outside strings, keeping offsets."""
    out = list(text)
    i = 0
    while i < len(text):
        if text[i] == '"':
            i = string_end(text, i)
            continue
        if text[i] == "#" or text.startswith("//", i):
            end = text.find("\n", i)
            end = len(text) if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = len(text) if end == -1 else end + 2
        else:
            i += 1
            continue
        for j in range(i, end):
            if out[j] != "\n":
                out[j] = " "
        i = end
    return "".join(out)


def line_of(text: str, offset: int) -> int:
    """Return the 1-based line number of offset in text."""
    return text.count("\n", 0, offset) + 1


def resource_blocks(text: str, rtype: str) -> list[ResourceBlock]:
    """Return every `resource "<rtype>"` block in comment-stripped text."""
    blocks: list[ResourceBlock] = []
    for match in RESOURCE_RE.finditer(text):
        if match.group("type") == rtype:
            brace = match.end() - 1
            line = line_of(text, match.start())
            blocks.append(
                ResourceBlock(rtype, match.group("name"), line, brace, group_end(text, brace))
            )
    return blocks


def split_top_level(text: str, start: int, end: int) -> list[tuple[int, str]]:
    """Split text[start:end] at top-level newlines/commas into (offset, chunk) pairs."""
    chunks: list[tuple[int, str]] = []
    i = chunk_start = start
    while i < end:
        char = text[i]
        if char == '"':
            i = string_end(text, i)
            continue
        if char in CLOSERS:
            i = group_end(text, i)
            continue
        if char in "\n,":
            chunks.append((chunk_start, text[chunk_start:i]))
            chunk_start = i + 1
        i += 1
    chunks.append((chunk_start, text[chunk_start:end]))
    return [(offset, chunk) for offset, chunk in chunks if chunk.strip()]


def literal_value(expr: str) -> str | None:
    """Return the text of expr when it is a plain string literal, else None."""
    if len(expr) >= 2 and expr[0] == expr[-1] == '"' and string_end(expr, 0) == len(expr):
        body = expr[1:-1]
        if "${" not in body and "%{" not in body:
            return body.replace('\\"', '"').replace("\\\\", "\\")
    return None


def map_entries(text: str, brace: int) -> list[EnvEntry]:
    """Parse the HCL object literal opening at text[brace] into env entries."""
    entries: list[EnvEntry] = []
    for offset, chunk in split_top_level(text, brace + 1, group_end(text, brace) - 1):
        if match := ENTRY_RE.match(chunk):
            value = match.group("value")
            line = line_of(text, offset + match.start("key"))
            entries.append(EnvEntry(match.group("key"), literal_value(value), value, line))
    return entries


def variables_value(
    text: str, start: int, end: int, *, nested: bool = False
) -> tuple[list[EnvEntry], list[str]]:
    """Parse `variables =` in text[start:end]; nested (inside parens) spans newlines."""
    entries: list[EnvEntry] = []
    opaque: list[str] = []
    rest: list[str] = []
    i = start
    while i < end and (nested or text[i] != "\n"):
        char = text[i]
        if char == "{":
            entries.extend(map_entries(text, i))
            i = group_end(text, i)
            continue
        if char == '"':
            i = string_end(text, i)
            continue
        if char in "([":
            inner_end = group_end(text, i)
            inner_entries, inner_opaque = variables_value(text, i + 1, inner_end - 1, nested=True)
            entries.extend(inner_entries)
            opaque.extend(inner_opaque)
            i = inner_end
            continue
        rest.append(char)
        i += 1
    opaque.extend(re.sub(r"\b(?:merge|tomap)\b|[,()\[\]]", " ", "".join(rest)).split())
    return entries, opaque


def lambda_env_maps(text: str) -> list[EnvMap]:
    """Return the env map of every aws_lambda_function in raw Terraform text."""
    clean = strip_comments(text)
    maps: list[EnvMap] = []
    for block in resource_blocks(clean, "aws_lambda_function"):
        entries: list[EnvEntry] = []
        opaque: list[str] = []
        for env in ENV_BLOCK_RE.finditer(clean, block.start, block.end):
            env_end = group_end(clean, env.end() - 1)
            for var in VARIABLES_RE.finditer(clean, env.end(), env_end):
                found, rest = variables_value(clean, var.end(), env_end - 1)
                entries.extend(found)
                opaque.extend(rest)
        maps.append(EnvMap(block.name, block.line, entries, opaque))
    return maps


def collect_files(roots: list[Path], suffix: str) -> list[Path]:
    """Return every file under roots with suffix; raise FileNotFoundError on a bad root."""
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            files.add(root)
        elif root.is_dir():
            files.update(p for p in root.rglob(f"*{suffix}") if ".terraform" not in p.parts)
        else:
            raise FileNotFoundError(f"no such file or directory: {root}")
    return sorted(p for p in files if p.suffix == suffix)


def check_file(path: Path) -> list[str]:
    """Return one finding per reserved env var set by a Lambda in path."""
    findings: list[str] = []
    for env_map in lambda_env_maps(path.read_text(encoding="utf-8")):
        findings.extend(
            f"{path.as_posix()}:{entry.line}: aws_lambda_function.{env_map.resource} sets "
            f"reserved env var {entry.name} — Lambda rejects the configuration "
            f"(InvalidParameterValueException); the runtime already provides it, delete it"
            for entry in env_map.entries
            if entry.name in RESERVED_ENV_NAMES
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    """Scan argv roots (files or dirs) for reserved Lambda env vars."""
    parser = argparse.ArgumentParser(description="Ban AWS-reserved Lambda env vars.")
    parser.add_argument("roots", nargs="+", type=Path, help="Terraform files or dirs")
    parser.add_argument("--exit-zero", action="store_true", help="report but exit 0")
    args = parser.parse_args(argv)
    try:
        files = collect_files(args.roots, ".tf")
        findings = [line for path in files for line in check_file(path)]
    except (OSError, UnicodeDecodeError) as exc:
        print(f"lambda-reserved-env: cannot check — {exc}", file=sys.stderr)
        return 2
    print(f"scanned={len(files)}", file=sys.stderr)
    if not files:
        print("lambda-reserved-env: no .tf files found — checked nothing", file=sys.stderr)
        return 2
    for line in findings:
        print(line)
    return 1 if findings and not args.exit_zero else 0


if __name__ == "__main__":
    sys.exit(main())
