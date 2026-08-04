#!/usr/bin/env bash
# Antigen — one-command proof.
#
#   ./run.sh              zero-dependency proof: tests + verify.py + the hero-arc demo
#                         (runs on any machine with Python 3.10+, no Docker, no keys)
#   ./run.sh live         the real path against a live, seeded DataHub GMS
#
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

banner() { printf '\n\033[1m── %s ──\033[0m\n' "$1"; }

if [[ "${1:-}" == "live" ]]; then
  banner "LIVE: seeding attack corpus into DataHub GMS"
  "$PY" seed_corpus.py
  banner "LIVE: verify.py (Part A graph-state gate + Part B hijack)"
  "$PY" verify.py --live
  exit 0
fi

banner "1/4  Test suite (detector + engine + verify)"
"$PY" tests/test_detect.py
"$PY" tests/test_cure.py
"$PY" tests/test_verify.py

banner "2/4  Near-miss false-positive gauntlet"
"$PY" seed_near_miss.py | tail -2

banner "3/4  verify.py — the reproducible proof"
"$PY" verify.py

banner "4/4  The hero arc (sweep -> defuse -> prove standing)"
"$PY" -m antigen demo --offline

banner "benchmark (p50/p95/p99)"
"$PY" bench.py --runs 20

printf '\n\033[1;32mAll green.\033[0m For the live DataHub path: ./run.sh live\n'
