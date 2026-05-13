"""Multi-agency fare calculator (Sprint 4b, Feature 1).

Given a list of legs `{agency_id, route_id, origin_stop_id,
destination_stop_id}`, look up each leg's matching fare product in
`fare_leg_rules` and sum to a total.

Resolution priority for each leg, against `fare_leg_rules`:

  1. route_and_od    — rule with network_id=route AND from_area=origin AND to_area=dest
  2. route_only      — rule with network_id=route AND from_area/to_area IS NULL
  3. od_only         — rule with from_area=origin AND to_area=dest AND network_id IS NULL
  4. agency_default  — first fare_products row for the agency
  5. no_data         — agency has no fare_products at all

The `matched_by` value on each result row identifies which step won so
planners can audit unexpected fares.

V1 transfer discounts: not applied. Sprint 4a Phase 2's loader did not
synthesise v1 transfers into `fare_transfer_rules` because the v2 model
is structurally different.  Real Bay Area transfer credits live at the
Clipper / rider-pass layer today, not the fare-rule layer.  The
calculator therefore sums legs and stops — when a Bay Area agency ships
true Fares v2 the `_apply_transfer_rules` stub becomes the extension
point.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.engine import Connection


# ── Pydantic request/response shapes ──────────────────────────────────────────

class Leg(BaseModel):
    agency_id:            str
    route_id:             Optional[str] = None
    origin_stop_id:       Optional[str] = None
    destination_stop_id:  Optional[str] = None


class FareRequest(BaseModel):
    legs: List[Leg] = []


class LegResult(BaseModel):
    agency_id:        str
    fare_product_id:  Optional[str]
    fare:             Optional[float]   # null = no_data
    matched_by:       str               # see closed set below


class FareResult(BaseModel):
    total:    float
    currency: str
    legs:     List[LegResult]


# Closed set of values surfaced in LegResult.matched_by — kept in sync with the
# UI's switch statement.  Anything past "route_only" is structurally less
# certain.
MATCHED_BY_VALUES = {
    "route_and_od",
    "route_only",
    "od_only",
    "agency_default",
    "no_data",
}


# ── Core resolution ───────────────────────────────────────────────────────────

def _resolve_leg(conn: Connection, leg: Leg) -> LegResult:
    """Apply the 5-step priority list against fare_leg_rules and
    fare_products for one leg.  Returns the chosen product or no_data."""

    def _fetch_fare(product_id: str) -> Optional[Decimal]:
        row = conn.execute(text("""
            SELECT amount, currency
            FROM fare_products
            WHERE agency_id = :agency_id
              AND fare_product_id = :product_id
        """), {"agency_id": leg.agency_id, "product_id": product_id}).first()
        return row[0] if row else None

    # GTFS Fares v1's `fare_rules.origin_id` / `destination_id` refer to
    # values in `stops.zone_id` (the farezone) — NOT stop_ids.  The Sprint
    # 4a loader stored them into `fare_leg_rules.from_area_id` /
    # `to_area_id` as-is.  Callers pass stop_ids on the leg, so we
    # translate each stop_id to its zone_id via `gtfs_stops` first.
    # Falls back to the stop_id itself when no zone is recorded (which
    # is how some agencies' rules are written).
    origin_keys      = _zone_candidates_for_stop(conn, leg.origin_stop_id)
    destination_keys = _zone_candidates_for_stop(conn, leg.destination_stop_id)

    # Step 1: route_and_od
    if leg.route_id and origin_keys and destination_keys:
        row = conn.execute(text("""
            SELECT fare_product_id
            FROM fare_leg_rules
            WHERE agency_id    = :agency_id
              AND network_id   = :route_id
              AND from_area_id = ANY(:origins)
              AND to_area_id   = ANY(:dests)
            LIMIT 1
        """), {
            "agency_id": leg.agency_id, "route_id": leg.route_id,
            "origins": origin_keys, "dests": destination_keys,
        }).first()
        if row:
            return _build_result(leg, row[0], _fetch_fare(row[0]), "route_and_od")

    # Step 2: route_only (rule with route, areas NULL — AC's shape)
    if leg.route_id:
        row = conn.execute(text("""
            SELECT fare_product_id
            FROM fare_leg_rules
            WHERE agency_id    = :agency_id
              AND network_id   = :route_id
              AND from_area_id IS NULL
              AND to_area_id   IS NULL
            LIMIT 1
        """), {"agency_id": leg.agency_id, "route_id": leg.route_id}).first()
        if row:
            return _build_result(leg, row[0], _fetch_fare(row[0]), "route_only")

    # Step 3: od_only (rule with areas, network NULL — BART's shape)
    if origin_keys and destination_keys:
        row = conn.execute(text("""
            SELECT fare_product_id
            FROM fare_leg_rules
            WHERE agency_id    = :agency_id
              AND network_id   IS NULL
              AND from_area_id = ANY(:origins)
              AND to_area_id   = ANY(:dests)
            LIMIT 1
        """), {
            "agency_id": leg.agency_id,
            "origins": origin_keys, "dests": destination_keys,
        }).first()
        if row:
            return _build_result(leg, row[0], _fetch_fare(row[0]), "od_only")

    # Step 4: agency_default
    row = conn.execute(text("""
        SELECT fare_product_id, amount
        FROM fare_products
        WHERE agency_id = :agency_id
        ORDER BY amount ASC NULLS LAST, fare_product_id ASC
        LIMIT 1
    """), {"agency_id": leg.agency_id}).first()
    if row:
        return _build_result(leg, row[0], row[1], "agency_default")

    # Step 5: no_data
    return LegResult(
        agency_id=leg.agency_id, fare_product_id=None,
        fare=None, matched_by="no_data",
    )


def _zone_candidates_for_stop(conn: Connection, stop_id: Optional[str]) -> List[str]:
    """Resolve a stop_id to the set of keys we'd try in `from_area_id` /
    `to_area_id`.  In practice this is `[zone_id, stop_id]` — try the
    farezone first (BART's shape), fall back to the stop_id (some
    smaller agencies key their rules directly by stop_id, and the
    test fixtures do this for simplicity)."""
    if not stop_id:
        return []
    row = conn.execute(text("""
        SELECT zone_id FROM gtfs_stops WHERE stop_id = :stop_id
    """), {"stop_id": stop_id}).first()
    zone_id = row[0] if row else None
    candidates = []
    if zone_id:
        candidates.append(zone_id)
    candidates.append(stop_id)
    return candidates


def _build_result(leg: Leg, product_id: str, fare: Optional[Decimal],
                  matched_by: str) -> LegResult:
    return LegResult(
        agency_id=leg.agency_id,
        fare_product_id=product_id,
        fare=float(fare) if fare is not None else None,
        matched_by=matched_by,
    )


def _apply_transfer_rules(
    conn: Connection,
    leg_results: List[LegResult],
) -> Decimal:
    """v1 mode: returns Decimal(0).  When v2 data arrives, this is the
    extension point — look up fare_transfer_rules between consecutive
    legs and return the total discount."""
    # Stub — see module docstring for rationale.  Args reserved.
    _ = (conn, leg_results)
    return Decimal("0")


# ── Public entry point ────────────────────────────────────────────────────────

def calculate_fare(conn: Connection, legs: List[Leg]) -> FareResult:
    """Compute total fare for a sequence of legs.  Empty `legs` returns
    total=0; legs in agencies with no fare data contribute 0 (so the
    sum still answers \"what the rider would pay for the legs we know\")
    and surface `matched_by=no_data` per leg so the UI can mark them."""
    leg_results = [_resolve_leg(conn, l) for l in legs]

    sum_legs = Decimal("0")
    currency = "USD"
    for r in leg_results:
        if r.fare is not None:
            sum_legs += Decimal(str(r.fare))

    discount = _apply_transfer_rules(conn, leg_results)
    total = sum_legs - discount

    return FareResult(
        total=float(total),
        currency=currency,
        legs=leg_results,
    )


# ── Dict adapter for callers that don't want Pydantic ─────────────────────────

def calculate_fare_dict(conn: Connection, legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convenience for in-process callers (e.g. the sampler) — accepts
    dict leg specs, returns a plain dict response."""
    typed = [Leg(**l) for l in legs]
    result = calculate_fare(conn, typed)
    return result.model_dump()
