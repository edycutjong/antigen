#!/usr/bin/env python3
"""fp_corpus.py — measure Antigen's false-positive rate on catalog descriptions
that the Antigen authors did not write.

Why this script exists
----------------------
Every negative example shipped inside this repo (``antigen/nearmiss.py``,
``tests/test_robustness.py``) was written by the same person who wrote the
detector. "0 false positives on 15 strings I wrote" is not a false-positive rate.
The number a platform team actually asks for is: *what is your flag rate on a real
catalog?*

This harvester collects real, public, human-written data-catalog descriptions from
external sources, runs :func:`antigen.detect.detect` over every one of them, and
prints the flag count and flag rate. It writes a manifest with exact provenance
(repository, pinned commit SHA, file path / portal domain, dataset id) and a
sha256 for every description so a judge can re-derive byte-identical input.

Sources
-------
``dbt``      Public dbt projects on GitHub. Repositories are *discovered* with the
             GitHub code-search API (``filename:dbt_project.yml``) rather than
             hand-picked, then each repo tarball is downloaded at a pinned commit
             SHA and every ``description:`` in its ``*.yml`` / ``*.yaml`` model,
             source, seed, snapshot and column definitions is extracted, plus every
             ``{% docs %}`` block in its ``*.md`` files. These strings are exactly
             the text dbt ships into DataHub's ``datasetProperties.description`` and
             ``editableSchemaMetadata`` field descriptions.

``socrata``  The Socrata Discovery API (``api.us.socrata.com``), which indexes the
             public open-data portals of several hundred cities, states and
             agencies. Each record carries a dataset description and a list of
             per-column descriptions — the open-data equivalent of a DataHub
             dataset description and its column documentation.

Usage
-----
    python scripts/fp_corpus.py harvest          # network; caches under scripts/.fp_corpus_cache/
    python scripts/fp_corpus.py run              # offline; detect() over the cache
    python scripts/fp_corpus.py report           # offline; writes docs/ artifacts

    python scripts/fp_corpus.py all              # harvest (if needed) + run + report

Flags: ``--refresh`` re-downloads, ``--dbt-repos N``, ``--socrata-datasets N``,
``--source dbt|socrata|all``.

Requirements: Python 3.10+. ``PyYAML`` is required for the ``dbt`` source only
(``pip install pyyaml``); the ``socrata`` source and the whole detection/report
path are stdlib. A GitHub token (``GITHUB_TOKEN``/``GH_TOKEN`` env var, or an
authenticated ``gh`` CLI) is required for the ``dbt`` source because the
code-search API refuses anonymous requests.

This script never writes to DataHub and never mutates anything. It only reads.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from antigen.detect import detect  # noqa: E402

CACHE_DIR = Path(__file__).resolve().parent / ".fp_corpus_cache"
DOCS_DIR = REPO_ROOT / "docs"

USER_AGENT = "antigen-fp-corpus/1.0 (+https://github.com/edycutjong/antigen)"

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #

# Defaults are the exact sizes used for docs/false-positive-study.md, so a bare
# `python scripts/fp_corpus.py all` reproduces the published run.
DEFAULT_DBT_REPOS = 220
DEFAULT_SOCRATA_DATASETS = 6000

GITHUB_API = "https://api.github.com"
CODELOAD = "https://codeload.github.com"
SOCRATA_API = "https://api.us.socrata.com/api/catalog/v1"

# Directories inside a repo that are not catalog metadata.
SKIP_DIR_PARTS = {
    ".github", "node_modules", ".venv", "venv", "site-packages",
    "target", "dbt_packages", "dbt_modules", ".git", "docs/_build",
}

# A pure dbt doc-reference is not natural-language prose — it is a pointer that dbt
# resolves at compile time to a docs block (which we harvest separately from the .md
# files). Keeping them would pad the denominator with strings that can never flag.
JINJA_DOC_REF = re.compile(r"^\{\{\s*doc\(\s*['\"][^'\"]+['\"]\s*\)\s*\}\}$")

DOCS_BLOCK = re.compile(
    r"\{%-?\s*docs\s+([A-Za-z0-9_.-]+)\s*-?%\}(.*?)\{%-?\s*enddocs\s*-?%\}",
    re.DOTALL,
)


# --------------------------------------------------------------------------- #
# Corpus item
# --------------------------------------------------------------------------- #

@dataclass
class Item:
    """One harvested description plus enough provenance to find it again."""

    text: str
    source: str          # "dbt" | "socrata"
    origin: str          # repo full_name | portal domain
    ref: str             # pinned commit sha | dataset id
    locator: str         # file path + node | column name / "<dataset>"
    kind: str            # model | column | source | seed | snapshot | docs-block | dataset

    def to_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "origin": self.origin,
            "ref": self.ref,
            "locator": self.locator,
            "kind": self.kind,
            "sha256": sha256(self.text),
        }

    @staticmethod
    def from_json(d: dict[str, Any]) -> Item:
        return Item(d["text"], d["source"], d["origin"], d["ref"], d["locator"], d["kind"])


def read_jsonl(path: Path) -> list[Item]:
    """Read a cache file one JSON object per line.

    Split on ``\n`` explicitly, never ``str.splitlines()``: real catalog prose
    contains U+2028/U+2029 line separators, which ``splitlines()`` treats as line
    breaks and ``json.dumps(ensure_ascii=False)`` writes out raw.
    """
    return [Item.from_json(json.loads(ln))
            for ln in path.read_text(encoding="utf-8").split("\n") if ln.strip()]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def _github_token() -> str | None:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        tok = os.environ.get(var)
        if tok:
            return tok
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=15
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed hosts
        return resp.read()


def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    return json.loads(http_get(url, headers, timeout).decode("utf-8"))


def gh_json(path: str, token: str, timeout: int = 60) -> Any:
    """GET the GitHub API with retry/backoff on secondary rate limits."""
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    delay = 2.0
    for attempt in range(6):
        try:
            return http_json(url, headers, timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                reset = exc.headers.get("x-ratelimit-reset")
                wait = delay
                if reset:
                    try:
                        wait = max(delay, min(90.0, float(reset) - time.time() + 2))
                    except ValueError:
                        pass
                print(f"    rate-limited ({exc.code}); sleeping {wait:.0f}s "
                      f"[attempt {attempt + 1}/6]", flush=True)
                time.sleep(wait)
                delay = min(delay * 2, 90)
                continue
            raise
    raise RuntimeError(f"giving up on {url} after repeated rate limiting")


# --------------------------------------------------------------------------- #
# Source 1 — public dbt projects on GitHub
# --------------------------------------------------------------------------- #

def discover_dbt_repos(token: str, want: int) -> list[dict[str, str]]:
    """Discover public repos that contain a dbt_project.yml, via code search.

    Repos are *found*, not chosen: the query is fixed and results are taken in the
    order GitHub returns them. The pinned commit SHA we record is what makes the
    corpus reproducible — GitHub's search ranking is not stable over time, the SHAs
    are.
    """
    found: dict[str, dict[str, str]] = {}
    # Code search caps at 10 pages x 100. One query is not enough to reach `want`
    # distinct repos, so we vary the query along an axis that does not bias the
    # *text* (repo size buckets), which GitHub treats as separate result sets.
    queries = [
        "filename:dbt_project.yml",
        "filename:schema.yml path:models",
        "filename:_models.yml",
        "filename:dbt_project.yml language:YAML",
        "filename:sources.yml path:models",
        "filename:schema.yaml path:models",
    ]
    for q in queries:
        if len(found) >= want:
            break
        for page in range(1, 11):
            if len(found) >= want:
                break
            params = urllib.parse.urlencode({"q": q, "per_page": 100, "page": page})
            try:
                data = gh_json(f"/search/code?{params}", token)
            except urllib.error.HTTPError as exc:
                print(f"    code-search stopped on '{q}' page {page}: HTTP {exc.code}")
                break
            items = data.get("items", [])
            if not items:
                break
            for it in items:
                repo = it["repository"]
                name = repo["full_name"]
                if name not in found:
                    found[name] = {"full_name": name, "html_url": repo["html_url"]}
            print(f"    q='{q}' page {page}: {len(found)} distinct repos so far", flush=True)
            time.sleep(7)  # code search allows 10 req/min authenticated
    return list(found.values())[:want]


def pin_repo(token: str, full_name: str) -> dict[str, str] | None:
    """Resolve default branch -> HEAD commit sha, plus license, for provenance."""
    try:
        meta = gh_json(f"/repos/{full_name}", token)
    except urllib.error.HTTPError:
        return None
    branch = meta.get("default_branch") or "main"
    try:
        commits = gh_json(f"/repos/{full_name}/commits?sha={branch}&per_page=1", token)
    except urllib.error.HTTPError:
        return None
    if not commits:
        return None
    lic = (meta.get("license") or {}).get("spdx_id") or "NOASSERTION"
    return {
        "full_name": full_name,
        "sha": commits[0]["sha"],
        "default_branch": branch,
        "license": lic,
        "size_kb": meta.get("size", 0),
        "html_url": meta.get("html_url", f"https://github.com/{full_name}"),
    }


MAX_REPO_KB = 80_000  # skip monorepos: the tarball cost is not worth the descriptions


def _iter_yaml_descriptions(doc: Any, path: list[str]) -> Iterator[tuple[str, str, str]]:
    """Yield (kind, name, description) for every described node in a dbt YAML doc."""
    if isinstance(doc, dict):
        desc = doc.get("description")
        if isinstance(desc, str) and desc.strip():
            kind = "node"
            for p in reversed(path):
                if p in ("models", "sources", "seeds", "snapshots", "columns",
                         "exposures", "metrics", "tables", "semantic_models",
                         "analyses", "macros", "arguments"):
                    kind = p.rstrip("s") if p != "analyses" else "analysis"
                    break
            name = doc.get("name") if isinstance(doc.get("name"), str) else "?"
            yield kind, name, desc
        for k, v in doc.items():
            if k == "description":
                continue
            yield from _iter_yaml_descriptions(v, path + [k] if isinstance(k, str) else path)
    elif isinstance(doc, list):
        for v in doc:
            yield from _iter_yaml_descriptions(v, path)


def harvest_dbt_repo(pin: dict[str, str]) -> list[Item]:
    """Download one repo tarball at its pinned sha and extract every description."""
    import yaml  # local import: only the dbt source needs PyYAML

    url = f"{CODELOAD}/{pin['full_name']}/tar.gz/{pin['sha']}"
    raw = http_get(url, timeout=120)
    items: list[Item] = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        members = [m for m in tf.getmembers() if m.isfile() and m.size < 2_000_000]
        names = {m.name for m in members}
        # Only treat this as a dbt project if it actually is one.
        if not any(n.endswith("dbt_project.yml") for n in names):
            return []
        for m in members:
            rel = m.name.split("/", 1)[1] if "/" in m.name else m.name
            parts = set(Path(rel).parts)
            if parts & SKIP_DIR_PARTS:
                continue
            low = rel.lower()
            if low.endswith((".yml", ".yaml")):
                if Path(rel).name in ("dbt_project.yml", "packages.yml", "profiles.yml",
                                      "selectors.yml", "dependencies.yml"):
                    continue
                fh = tf.extractfile(m)
                if fh is None:
                    continue
                try:
                    doc = yaml.safe_load(fh.read().decode("utf-8", "replace"))
                except Exception:
                    continue
                if not isinstance(doc, dict):
                    continue
                # A dbt *schema file* is identified by its top-level keys. This keeps
                # CI configs, docker-compose files and OpenAPI specs — which also use
                # `description:` — out of the corpus.
                if not (doc.keys() & {"models", "sources", "seeds", "snapshots",
                                      "exposures", "metrics", "semantic_models",
                                      "analyses", "macros"}):
                    continue
                for kind, name, desc in _iter_yaml_descriptions(doc, []):
                    items.append(Item(desc, "dbt", pin["full_name"], pin["sha"],
                                      f"{rel}#{name}", kind))
            elif low.endswith(".md"):
                fh = tf.extractfile(m)
                if fh is None:
                    continue
                text = fh.read().decode("utf-8", "replace")
                if "{% docs" not in text and "{%- docs" not in text:
                    continue
                for name, body in DOCS_BLOCK.findall(text):
                    if body.strip():
                        items.append(Item(body, "dbt", pin["full_name"], pin["sha"],
                                          f"{rel}#{name}", "docs-block"))
    return items


def harvest_dbt(want_repos: int, refresh: bool) -> tuple[list[Item], dict[str, Any]]:
    cache = CACHE_DIR / "dbt"
    cache.mkdir(parents=True, exist_ok=True)
    items_path = cache / "descriptions.jsonl"
    pins_path = cache / "repos.json"

    if items_path.exists() and pins_path.exists() and not refresh:
        print("  [dbt] using cache")
        items = read_jsonl(items_path)
        return items, json.loads(pins_path.read_text())

    token = _github_token()
    if token is None:
        print("  [dbt] SKIPPED — no GitHub token (set GITHUB_TOKEN or run `gh auth login`)")
        return [], {"repos": [], "skipped": "no-github-token"}
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("  [dbt] SKIPPED — PyYAML not installed (`pip install pyyaml`)")
        return [], {"repos": [], "skipped": "no-pyyaml"}

    print(f"  [dbt] discovering up to {want_repos} repos via code search…")
    repos = discover_dbt_repos(token, want_repos)
    print(f"  [dbt] {len(repos)} candidate repos; pinning commit SHAs…")

    pins: list[dict[str, str]] = []
    for i, r in enumerate(repos, 1):
        pin = pin_repo(token, r["full_name"])
        if pin and int(pin.get("size_kb") or 0) <= MAX_REPO_KB:
            pins.append(pin)
        if i % 25 == 0:
            print(f"    pinned {i}/{len(repos)}", flush=True)
        time.sleep(0.15)

    items: list[Item] = []
    kept_pins: list[dict[str, Any]] = []
    for i, pin in enumerate(pins, 1):
        try:
            got = harvest_dbt_repo(pin)
        except Exception as exc:  # noqa: BLE001 — one bad repo must not kill the run
            print(f"    {pin['full_name']}: {type(exc).__name__}: {exc}")
            continue
        if got:
            items.extend(got)
            kept_pins.append({**pin, "descriptions": len(got)})
        print(f"    [{i}/{len(pins)}] {pin['full_name']}: {len(got)} descriptions "
              f"(running total {len(items)})", flush=True)
        time.sleep(0.4)

    with items_path.open("w") as fh:
        for it in items:
            fh.write(json.dumps(it.to_json(), ensure_ascii=False) + "\n")
    meta = {"query_set": "code-search filename:dbt_project.yml (+5 sibling queries)",
            "repos": kept_pins}
    pins_path.write_text(json.dumps(meta, indent=2))
    return items, meta


# --------------------------------------------------------------------------- #
# Source 2 — Socrata open-data portals
# --------------------------------------------------------------------------- #

def harvest_socrata(want_datasets: int, refresh: bool) -> tuple[list[Item], dict[str, Any]]:
    cache = CACHE_DIR / "socrata"
    cache.mkdir(parents=True, exist_ok=True)
    items_path = cache / "descriptions.jsonl"
    meta_path = cache / "meta.json"

    if items_path.exists() and meta_path.exists() and not refresh:
        print("  [socrata] using cache")
        items = read_jsonl(items_path)
        return items, json.loads(meta_path.read_text())

    items: list[Item] = []
    domains: dict[str, int] = {}
    scroll_id = ""
    seen = 0
    page = 0
    while seen < want_datasets:
        # The Discovery API rejects `order` together with `scroll_id`; scrolling is
        # implicitly ordered by dataset id, so the first page is unordered and every
        # subsequent page resumes from the last id we saw.
        params: dict[str, Any] = {"only": "dataset", "limit": 100}
        if scroll_id:
            params["scroll_id"] = scroll_id
        else:
            params["order"] = "dataset_id"
        url = f"{SOCRATA_API}?{urllib.parse.urlencode(params)}"
        try:
            data = http_json(url, timeout=60)
        except Exception as exc:  # noqa: BLE001
            print(f"    socrata page {page} failed: {type(exc).__name__}: {exc}")
            break
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            res = r.get("resource", {})
            dom = (r.get("metadata") or {}).get("domain", "?")
            did = res.get("id", "?")
            domains[dom] = domains.get(dom, 0) + 1
            desc = res.get("description")
            if isinstance(desc, str) and desc.strip():
                items.append(Item(desc, "socrata", dom, did, "<dataset>", "dataset"))
            cols = res.get("columns_description") or []
            names = res.get("columns_name") or []
            for j, cd in enumerate(cols):
                if isinstance(cd, str) and cd.strip():
                    cname = names[j] if j < len(names) else f"col{j}"
                    items.append(Item(cd, "socrata", dom, did, cname, "column"))
            scroll_id = did
        seen += len(results)
        page += 1
        print(f"    [socrata] page {page}: {seen} datasets, {len(items)} descriptions",
              flush=True)
        time.sleep(0.35)

    with items_path.open("w") as fh:
        for it in items:
            fh.write(json.dumps(it.to_json(), ensure_ascii=False) + "\n")
    meta = {"api": SOCRATA_API, "datasets_scanned": seen,
            "portals": len(domains),
            "top_portals": sorted(domains.items(), key=lambda kv: -kv[1])[:30]}
    meta_path.write_text(json.dumps(meta, indent=2))
    return items, meta


# --------------------------------------------------------------------------- #
# Corpus assembly
# --------------------------------------------------------------------------- #

@dataclass
class Corpus:
    items: list[Item] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def dedup(self) -> list[Item]:
        """One row per distinct description string.

        dbt packages copy each other constantly (every Fivetran connector package
        repeats the same column docs), and open-data portals republish the same
        boilerplate. Counting a string once is the only defensible denominator.
        """
        seen: set[str] = set()
        out: list[Item] = []
        for it in self.items:
            key = it.text.strip()
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out


def is_usable(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if JINJA_DOC_REF.match(t):
        # A pointer, not prose — the prose it points at is harvested from the .md.
        return False
    return True


# Antigen's detector is an English-language rule, so a non-English description is
# clean for free and would flatter the headline rate if it were counted silently.
# This crude stopword probe is reported alongside the headline number, NOT used to
# filter the corpus — the whole corpus is scanned either way.
_EN_STOPWORDS = re.compile(
    r"\b(?:the|and|of|for|to|is|are|in|with|this|that|by|from|each|per|which|"
    r"when|contains|column|data)\b",
    re.IGNORECASE,
)


def looks_english(text: str) -> bool:
    return bool(_EN_STOPWORDS.search(text))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_harvest(args: argparse.Namespace) -> Corpus:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    items: list[Item] = []
    meta_path = CACHE_DIR / "meta.json"
    # Merge rather than overwrite so `--source dbt` and `--source socrata` can be run
    # as separate invocations without losing each other's provenance.
    meta: dict[str, Any] = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if args.source in ("all", "dbt"):
        got, m = harvest_dbt(args.dbt_repos, args.refresh)
        items += got
        meta["dbt"] = m
    if args.source in ("all", "socrata"):
        got, m = harvest_socrata(args.socrata_datasets, args.refresh)
        items += got
        meta["socrata"] = m
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"\nharvested {len(items)} raw descriptions")
    return Corpus(items, meta)


def load_corpus() -> Corpus:
    items: list[Item] = []
    for sub in ("dbt", "socrata"):
        p = CACHE_DIR / sub / "descriptions.jsonl"
        if p.exists():
            items += read_jsonl(p)
    meta_p = CACHE_DIR / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    if not items:
        sys.exit("no cached corpus — run `python scripts/fp_corpus.py harvest` first")
    return Corpus(items, meta)


def run_detector(corpus: Corpus) -> dict[str, Any]:
    unique = [it for it in corpus.dedup() if is_usable(it.text)]
    by_source: dict[str, dict[str, int]] = {}
    flagged: list[dict[str, Any]] = []
    by_kind: dict[str, dict[str, int]] = {}
    english = 0
    english_flagged = 0
    for it in unique:
        stats = by_source.setdefault(it.source, {"scanned": 0, "flagged": 0})
        stats["scanned"] += 1
        kstats = by_kind.setdefault(f"{it.source}:{it.kind}", {"scanned": 0, "flagged": 0})
        kstats["scanned"] += 1
        en = looks_english(it.text)
        english += en
        d = detect(it.text)
        if d.flagged:
            stats["flagged"] += 1
            kstats["flagged"] += 1
            english_flagged += en
            flagged.append({
                **it.to_json(),
                "score": d.score,
                "signals": d.signals,
                "categories": [c.value for c in d.categories],
                "hidden_unicode": d.hidden_unicode,
                "matched_text": d.matched_text,
                "rule_fired": d.rule_fired,
            })
    by_signal: dict[str, int] = {}
    for f in flagged:
        key = "+".join(f["signals"]) or "?"
        by_signal[key] = by_signal.get(key, 0) + 1
    return {
        "raw_descriptions": len(corpus.items),
        "unique_scanned": len(unique),
        "flagged": len(flagged),
        "flag_rate": (len(flagged) / len(unique)) if unique else 0.0,
        "english_like_scanned": english,
        "english_like_flagged": english_flagged,
        "english_like_flag_rate": (english_flagged / english) if english else 0.0,
        "by_source": by_source,
        "by_kind": by_kind,
        "by_signal": by_signal,
        "flagged_items": flagged,
        "corpus_digest": sha256("\n".join(sorted(sha256(i.text) for i in unique))),
    }


def print_summary(res: dict[str, Any], corpus: Corpus) -> None:
    print("\n" + "=" * 72)
    print("ANTIGEN FALSE-POSITIVE STUDY — external corpus")
    print("=" * 72)
    print(f"raw descriptions harvested : {res['raw_descriptions']:,}")
    print(f"unique descriptions scanned: {res['unique_scanned']:,}")
    print(f"flagged by detect()        : {res['flagged']:,}")
    rate = res["flag_rate"]
    per10k = rate * 10_000
    print(f"flag rate                  : {rate * 100:.4f} %   ({per10k:.1f} per 10,000)")
    en, enf = res["english_like_scanned"], res["english_like_flagged"]
    print(f"English-like subset        : {en:,} scanned, {enf:,} flagged "
          f"({res['english_like_flag_rate'] * 100:.4f} %)")
    print(f"corpus digest (sha256)     : {res['corpus_digest']}")
    print("-" * 72)
    for src, st in sorted(res["by_source"].items()):
        r = st["flagged"] / st["scanned"] if st["scanned"] else 0
        print(f"  {src:10s} scanned {st['scanned']:>7,}   flagged {st['flagged']:>4,}   "
              f"rate {r * 100:.4f}%")
    for kind, st in sorted(res.get("by_kind", {}).items()):
        r = st["flagged"] / st["scanned"] if st["scanned"] else 0
        print(f"    {kind:<24s} scanned {st['scanned']:>7,}   flagged {st['flagged']:>4,}   "
              f"rate {r * 100:.4f}%")
    dbt_meta = corpus.meta.get("dbt", {})
    soc_meta = corpus.meta.get("socrata", {})
    if dbt_meta.get("repos"):
        print(f"  dbt provenance : {len(dbt_meta['repos'])} public repos, pinned commit SHAs")
    if soc_meta.get("portals"):
        print(f"  socrata prov.  : {soc_meta['datasets_scanned']:,} datasets across "
              f"{soc_meta['portals']} portals")
    if res.get("by_signal"):
        print("-" * 72)
        for sig, n in sorted(res["by_signal"].items(), key=lambda kv: -kv[1]):
            print(f"  signal {sig:<40s} {n:>4,}")
    print("-" * 72)
    if res["flagged"]:
        print("\nFLAGGED DESCRIPTIONS (verbatim, for human adjudication)\n")
        for i, f in enumerate(res["flagged_items"], 1):
            print(f"[{i}] {f['source']} · {f['origin']} · {f['locator']}")
            print(f"    signals={f['signals']} score={f['score']}")
            print(f"    why: {f['rule_fired']}")
            body = f["text"].strip().replace("\n", "\\n")
            print(f"    {body[:600]}{'…' if len(body) > 600 else ''}")
            print()
    else:
        print("\nNo description in the external corpus flagged.\n")


def cmd_report(res: dict[str, Any], corpus: Corpus) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    unique = [it for it in corpus.dedup() if is_usable(it.text)]
    manifest = {
        "generated_by": "scripts/fp_corpus.py",
        "detector": "antigen.detect.detect (FLAG_THRESHOLD=2)",
        "raw_descriptions": res["raw_descriptions"],
        "unique_scanned": res["unique_scanned"],
        "flagged": res["flagged"],
        "flag_rate": res["flag_rate"],
        "english_like_scanned": res["english_like_scanned"],
        "english_like_flagged": res["english_like_flagged"],
        "english_like_flag_rate": res["english_like_flag_rate"],
        "corpus_digest": res["corpus_digest"],
        "by_source": res["by_source"],
        "by_kind": res.get("by_kind", {}),
        "by_signal": res.get("by_signal", {}),
        "provenance": corpus.meta,
        "flagged_items": res["flagged_items"],
    }
    out = DOCS_DIR / "fp-corpus-manifest.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    # Per-item fingerprints. The raw text is NOT redistributed — see the licensing
    # note in docs/false-positive-study.md — so this file plus the provenance in the
    # manifest is how a judge checks that a re-harvest produced the same corpus.
    # Hash is truncated to 16 hex chars (64 bits) purely to keep the file readable;
    # the full sha256 of every *flagged* item is in the manifest.
    hashes = DOCS_DIR / "fp-corpus-hashes.txt"
    with hashes.open("w") as fh:
        fh.write("# sha256[:16]\tsource\torigin\tflagged\n")
        flagged_hashes = {f["sha256"] for f in res["flagged_items"]}
        for it in sorted(unique, key=lambda i: (i.source, i.origin, i.locator)):
            h = sha256(it.text)
            mark = "FLAG" if h in flagged_hashes else ""
            fh.write(f"{h[:16]}\t{it.source}\t{it.origin}\t{mark}\n")
    print(f"\nwrote {out.relative_to(REPO_ROOT)}")
    print(f"wrote {hashes.relative_to(REPO_ROOT)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["harvest", "run", "report", "all"], nargs="?",
                    default="all")
    ap.add_argument("--source", choices=["all", "dbt", "socrata"], default="all")
    ap.add_argument("--dbt-repos", type=int, default=DEFAULT_DBT_REPOS)
    ap.add_argument("--socrata-datasets", type=int, default=DEFAULT_SOCRATA_DATASETS)
    ap.add_argument("--refresh", action="store_true", help="ignore cache and re-download")
    args = ap.parse_args(argv)

    if args.command == "harvest":
        cmd_harvest(args)
        return 0

    corpus = cmd_harvest(args) if args.command == "all" else load_corpus()
    res = run_detector(corpus)
    print_summary(res, corpus)
    if args.command in ("report", "all"):
        cmd_report(res, corpus)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
