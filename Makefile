.PHONY: help install dev test cov lint typecheck verify demo bench security-scan examples ci

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package (core is stdlib-only)
	pip install -e .

dev:  ## Install dev tooling (ruff, mypy, pytest, pip-audit)
	pip install -e ".[dev]"

test:  ## Run the test suite
	pytest

cov:  ## Run tests with coverage (fails under 100%)
	pytest --cov=antigen --cov-report=term-missing --cov-fail-under=100

lint:  ## Lint with ruff
	ruff check .

typecheck:  ## Type-check with mypy (advisory)
	mypy antigen || true

verify:  ## Run the reproducible graph-state proof (verify.py Part A + hijack)
	python verify.py

demo:  ## Run the hero arc offline (sweep -> defuse -> certify -> prove)
	python -m antigen demo --offline

bench:  ## Benchmark scan+cure (p50/p95/p99)
	python bench.py --runs 20

examples:  ## Regenerate examples/ from the corpus
	python scripts/generate_examples.py

security-scan:  ## npm-audit equivalent: pip-audit + secret hygiene reminder
	@echo "=== PIP-AUDIT (dev + live extras) ==="
	pip-audit --desc || true
	@echo ""
	@echo "Core is stdlib-only; credentials belong in ~/.config, never in the tree."

ci:  ## Full local gate: lint + typecheck + tests + verify
	$(MAKE) lint && $(MAKE) typecheck && $(MAKE) cov && $(MAKE) verify
