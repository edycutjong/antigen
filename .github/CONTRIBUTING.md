# Contributing

Thanks for your interest in improving Antigen! 🧬

Antigen is a prompt-injection immune system for the DataHub metadata graph. The
detector, engine, and `verify.py` graph-state proof are **Python standard library
only**, so you can develop and test the whole thing with no Docker and no API keys.

## Getting Started
1. Fork the repo and branch from `main`: `git checkout -b feat/your-feature`
2. Install dev tooling: `make dev`  (or `pip install -e ".[dev]"`)
3. Run the proof offline: `make verify` and `python -m antigen demo --offline`

## Before You Open a PR
- `make ci` passes — that is `ruff check .`, `mypy antigen` (advisory), `pytest --cov`,
  and `python verify.py` (the graph-state gate).
- Add or update tests for any behavior change. New injection categories need a
  corpus entry **and** a near-miss guard so false positives stay at zero.
- If you touch the corpus or detector, regenerate examples: `make examples` (CI checks
  `examples/` is in sync).
- Keep commits conventional (`feat:`, `fix:`, `docs:`, `chore:`).

## What makes a good detector change
- Prefer the scored-rule approach (co-occurrence of a reader-directed imperative and an
  agent-action object) over bare keyword matches — the 0-false-positive guarantee on the
  near-miss gauntlet is the bar.
- Never write recovered payload text back to the graph — only irreversible hashes and
  graph-safe signal labels. `verify.py` Part A asserts this.

## Reporting Bugs / Requesting Features
Open an issue using the provided templates. Include repro steps, expected vs. actual
behavior, and (for detector issues) the exact string that mis-classified.

## Security
Found a way to bypass detection or a vulnerability in Antigen itself? Please follow
[SECURITY.md](SECURITY.md) — do not open a public issue.
