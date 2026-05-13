#!/usr/bin/env python3
"""Sprint 5a acceptance sweep — runnable proof that the sprint is done.

Walks the 9 verification criteria from
docs/superpowers/specs/2026-05-13-sprint-5a-design.md against the
running backend + frontend.  Exits non-zero on any failure so it can
gate a CI check or a manual pre-merge sanity step.

Usage:
  # services must be running (docker compose up -d)
  python3 scripts/sprint-5a-acceptance.py

Env:
  BACKEND_URL      default http://localhost:8001
  FRONTEND_URL     default http://localhost:5173
  BACKEND_API_KEY  required when the backend has an api key configured
                   (defaults to the dev value: 'change_me_backend_api_key')
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE     = os.environ.get("BACKEND_URL",  "http://localhost:8001")
FRONTEND = os.environ.get("FRONTEND_URL", "http://localhost:5173")
KEY      = os.environ.get("BACKEND_API_KEY", "change_me_backend_api_key")

H_GET = {"X-API-Key": KEY}


def get(url: str) -> dict | list:
    req = urllib.request.Request(f"{BASE}{url}", headers=H_GET)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}")
    if detail:
        print(f"         {detail}")


def note(label: str, detail: str = "") -> None:
    print(f"  [NOTE] {label}")
    if detail:
        print(f"         {detail}")


print("=" * 70)
print("Sprint 5a acceptance sweep — see specs/2026-05-13-sprint-5a-design.md")
print("=" * 70)


# ── #1/#2/#3 fetch the feature collection once and inspect it ────────────────
print("\n#1-#3  GET /equity/fare-burden — endpoint + schema + non-empty")
fc = get("/equity/fare-burden?limit=5000")
features = fc.get("features") if isinstance(fc, dict) else None
check("FeatureCollection type",
      isinstance(fc, dict) and fc.get("type") == "FeatureCollection",
      f"type = {fc.get('type') if isinstance(fc, dict) else type(fc).__name__}")
check("features non-empty (>= 2000)",
      isinstance(features, list) and len(features) >= 2000,
      f"{len(features) if isinstance(features, list) else 0} features")

# Schema shape — every feature should have these props.
expected_props = {
    "cell_id", "median_fare_to_sf", "median_fare_to_oakland", "median_fare_to_sfo",
    "worst_fare", "burden_pct", "burden_tier", "reachable_anchor_count",
    "population", "median_household_income",
}
first_props = set((features or [{}])[0].get("properties", {}).keys())
check("feature.properties has all 10 expected keys",
      expected_props.issubset(first_props),
      f"missing: {expected_props - first_props or '∅'}")


# ── #4 burden tier distribution ──────────────────────────────────────────────
print("\n#4  Burden-tier distribution (>= 50 cells in high|very_high)")
tier_counts: dict[str | None, int] = {}
income_set = 0
for f in features or []:
    p = f.get("properties", {}) or {}
    t = p.get("burden_tier")
    tier_counts[t] = tier_counts.get(t, 0) + 1
    if p.get("median_household_income") is not None:
        income_set += 1
high_or_very = tier_counts.get("high", 0) + tier_counts.get("very_high", 0)
if income_set == 0:
    # Honest soft-fail: this is the documented blocker when ACS hasn't been
    # reloaded with B19013_001E.  The compute job ran (we have 2k+ rows)
    # but burden_pct is None on every cell.
    check("median_household_income is populated on >= 1 cell",
          False,
          ("0/{} cells have income — run the ACS loader with a Census API key set "
           "(CENSUS_API_KEY in backend/.env), then re-run step 14 of the ETL.")
              .format(len(features) if features else 0))
    check("high|very_high tier cells >= 50",
          False,
          f"high={tier_counts.get('high', 0)} very_high={tier_counts.get('very_high', 0)} "
          f"(0 because income is NULL — fix the above)")
else:
    check("high|very_high tier cells >= 50",
          high_or_very >= 50,
          f"high={tier_counts.get('high', 0)} very_high={tier_counts.get('very_high', 0)} "
          f"(total tiered = {sum(v for k, v in tier_counts.items() if k)})")


# ── #5 unreachable cells (the East Bay reality) ──────────────────────────────
print("\n#5  Unreachable-cell count (>= 100 with reachable_anchor_count = 0)")
unreachable = sum(
    1 for f in (features or [])
    if (f.get("properties", {}) or {}).get("reachable_anchor_count") == 0
)
check("unreachable cells >= 100",
      unreachable >= 100,
      f"{unreachable} cells with reachable_anchor_count = 0")


# ── #6 anchor-weight re-weighting works ──────────────────────────────────────
print("\n#6  anchor_weights query param re-weights worst_fare")
re_weighted = get("/equity/fare-burden?anchor_weights=sf:1,oakland:0.1,sfo:0.1&limit=2000")
rw_features = re_weighted.get("features", []) if isinstance(re_weighted, dict) else []
# At least some cells should have a *different* worst_fare under the new
# weights (any cell where Oakland or SFO was previously the binding anchor).
diff_cells = 0
default_by_id = {
    f["properties"]["cell_id"]: f["properties"].get("worst_fare")
    for f in (features or []) if f.get("properties")
}
for f in rw_features:
    p = f.get("properties", {}) or {}
    cid = p.get("cell_id")
    if cid in default_by_id and p.get("worst_fare") is not None:
        if default_by_id[cid] is not None and abs(default_by_id[cid] - p["worst_fare"]) > 0.01:
            diff_cells += 1
check("re-weighting changes worst_fare on >= 50 cells",
      diff_cells >= 50,
      f"{diff_cells} cells differ when Oakland+SFO are deprioritised")


# ── #7/#8 frontend reachability (vitest covers behaviour) ────────────────────
print("\n#7  Planning → Fare Burden renders KPI strip + map + top-10 list")
print("    (vitest: FareBurden.test.tsx — 4 cases)")
print("#8  CSV export covers all per-cell fields")
print("    (vitest: 'Export button is wired with all per-cell fields')")
try:
    with urllib.request.urlopen(FRONTEND, timeout=5) as r:
        check("frontend reachable", r.status == 200, f"http {r.status} {FRONTEND}")
except Exception as e:
    check("frontend reachable", False, f"{type(e).__name__}: {e}")


# ── #9 test count totals ─────────────────────────────────────────────────────
print("\n#9  Backend >= 119, Frontend >= 98 — run pytest + vitest separately:")
print("    cd backend && .venv/bin/pytest -q")
print("    cd frontend && npx vitest run")


# ── Summary ──────────────────────────────────────────────────────────────────
n_pass = sum(1 for _, ok, _ in results if ok)
n_total = len(results)
print("\n" + "=" * 70)
print(f"Result: {n_pass}/{n_total} live checks PASS")
if n_pass < n_total:
    print("Failures:")
    for label, ok, detail in results:
        if not ok:
            print(f"  - {label}: {detail}")
print("=" * 70)
sys.exit(0 if n_pass == n_total else 1)
