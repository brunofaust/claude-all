# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Repackaged as a proper Python package: `agents/`, `skills/`, `hooks/`, `instructions/`,
  `mcps/`, `plugins/`, and `tools/` moved under `src/claude_all/`; `claude-all.py` renamed to
  `src/claude_all/cli.py`.
- Added a `hatchling` build backend and a `claude-all` console-script entry point so the
  installer can be installed with `uv tool install git+https://github.com/brunofaust/claude-all.git`,
  in addition to the existing git-clone + `uv sync --dev` development setup.
- Added `python-semantic-release` + `commitizen` release automation, modeled on
  `brunofaust/codecongruence`: conventional commits drive version bumps and CHANGELOG
  generation, cut by merging a `release/x.y.z` branch into `main`.
- Added `codecongruence.toml`, scoping the `duplicate_functions` rule away from
  `src/claude_all/hooks/`, skill `hook.py` companions, and `regression-gates/checkers/` —
  these are individually-symlinked or copy-into-your-project standalone scripts that
  can't share code via imports, so their small dispatch helpers are expected to overlap.
- Documented missing docstring parameters on `purge_hook_entries`, `context_tokens`,
  `load_baseline`, `compare`, `calls_with_scope`, `literal`, `parse_file`, and `nudge`.
