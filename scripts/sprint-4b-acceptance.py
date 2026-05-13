#!/usr/bin/env python3
"""Sprint 4b acceptance sweep — runnable proof that the sprint is done.

Walks the 8 verification criteria from
docs/superpowers/specs/2026-05-13-sprint-4b-design.md against the
running backend + frontend.  Exits non-zero on any failure so it can
gate a CI check or a manual pre-merge sanity step.

Usage:
  # services must be running (docker compose up -d)
  python3 scripts/sprint-4b-acceptance.py

Env:
  BACKEND_URL    default http://localhost:8001
  FRONTEND_URL   default http://localhost:5173
  BACKEND_API_KEY  required when the backend has an api key configured
                   (defaults to the dev value in .env: 'change_me_backend_api_key')
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE         = os.environ.get("BACKEND_URL",  "http://localhost:8001")
FRONTEND     = os.environ.get("FRONTEND_URL", "http://localhost:5173")
KEY          = os.environ.get("BACKEND_API_KEY", "change_me_backend_api_key")

H_GET  = {"X-API-Key": KEY}
H_POST = {"X-API-Key": KEY, "Content-Type": "application/json"}


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{url}", headers=H_POST,
        data=json.dumps(payload).encode(), method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get(url: str) -> dict | list:
    req = urllib.request.Request(f"{BASE}{url}", headers=H_GET)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


results: list[tuple[str, bool, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}")
    if detail:
        print(f"         {detail}")


print("=" * 70)
print("Sprint 4b acceptance sweep — see specs/2026-05-13-sprint-4b-design.md")
print("=" * 70)


# ── #1 single AC leg ─────────────────────────────────────────────────────────
print("\n#1  POST /fares/calculate with a single AC leg")
body = post("/fares/calculate", {"legs": [{"agency_id": "AC", "route_id": "O"}]})
ac_product = body["legs"][0]["fare_product_id"]
ac_fare    = body["legs"][0]["fare"]
expected = get(f"/fares/products?agency_id=AC")
expected_amt = next((p["amount"] for p in expected
                     if p["fare_product_id"] == ac_product), None)
check("total > 0", body["total"] > 0,
      f"total ${body['total']}, product {ac_product}")
check("fare matches fare_products.amount",
      ac_fare == expected_amt,
      f"calculator ${ac_fare} == fare_products.amount ${expected_amt}")


# ── #2 BART OD leg ───────────────────────────────────────────────────────────
print("\n#2  POST /fares/calculate with a BART OD leg")
body = post("/fares/calculate", {"legs": [
    {"agency_id": "BA",
     "origin_stop_id":      "902301",     # Coliseum
     "destination_stop_id": "906309"},    # San Bruno
]})
ba_leg = body["legs"][0]
check("total > 0", body["total"] > 0, f"total ${body['total']}")
check("fare_product_id is BART numeric",
      str(ba_leg["fare_product_id"] or "").isdigit(),
      f"product {ba_leg['fare_product_id']}")
check("matched_by == 'od_only'",
      ba_leg["matched_by"] == "od_only",
      f"matched_by {ba_leg['matched_by']}")


# ── #3 two-leg sums without v1 transfer discount ─────────────────────────────
print("\n#3  POST /fares/calculate with two legs (AC + BART)")
body = post("/fares/calculate", {"legs": [
    {"agency_id": "AC", "route_id": "O"},
    {"agency_id": "BA",
     "origin_stop_id":      "902301",
     "destination_stop_id": "906309"},
]})
ac_fare = body["legs"][0]["fare"]
ba_fare = body["legs"][1]["fare"]
check("total = sum of legs (no v1 transfer discount)",
      abs(body["total"] - (ac_fare + ba_fare)) < 0.01,
      f"total ${body['total']} == ${ac_fare} + ${ba_fare}")


# ── #4 Berkeley → Embarcadero corridor sample ────────────────────────────────
print("\n#4  POST /fares/sample-corridor (Downtown Berkeley → Embarcadero)")
body = post("/fares/sample-corridor", {
    "origin":      {"lat": 37.871, "lng": -122.272},
    "destination": {"lat": 37.793, "lng": -122.397},
    "n": 30,
})
check("n_sampled >= 5", body["n_sampled"] >= 5,
      f"n_sampled = {body['n_sampled']}")
check("median_fare in [$2.00, $10.00]",
      body["median_fare"] is not None and 2.0 <= body["median_fare"] <= 10.0,
      f"median ${body['median_fare']}")
check("agencies populated OR notice indicates no-direct-connection",
      bool(body["agencies"]) or "no direct connection" in (body["notice"] or ""),
      f"agencies={body['agencies']}, notice={body['notice']!r}")
check("at least one entry in high_burden_cells",
      len(body["high_burden_cells"]) >= 1,
      (f"{len(body['high_burden_cells'])} cells, top burden = "
       f"{body['high_burden_cells'][0]['burden']:.3f}"
       if body["high_burden_cells"] else "none"))


# ── #5/#6/#7 frontend reachability (vitest covers behaviour) ─────────────────
print("\n#5  Planning → Fares renders + click cycle + charts")
print("    (vitest: Fares.test.tsx — 6 cases)")
print("#6  Top 10 high-burden cells panel populated")
print("    (vitest: 'renders the high-burden cells list')")
print("#7  'Clear pins' resets selection to state 0")
print("    (vitest: 'Clear pins resets selection and returns to empty state')")
try:
    with urllib.request.urlopen(FRONTEND, timeout=5) as r:
        check("frontend reachable", r.status == 200, f"http {r.status} {FRONTEND}")
except Exception as e:
    check("frontend reachable", False, f"{type(e).__name__}: {e}")


# ── #8 test count totals ─────────────────────────────────────────────────────
print("\n#8  Backend >= 107, Frontend >= 94 — run pytest + vitest separately:")
print("    cd backend && .venv/bin/pytest -q")
print("    cd frontend && npx vitest run")


# ── Summary ──────────────────────────────────────────────────────────────────
n_pass = sum(1 for _, ok, _ in results if ok)
n_total = len(results)
print("\n" + "=" * 70)
print(f"Result: {n_pass}/{n_total} live checks PASS")
print("=" * 70)
sys.exit(0 if n_pass == n_total else 1)
