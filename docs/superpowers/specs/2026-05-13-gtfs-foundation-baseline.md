# GTFS Foundation Fix — Pre-Migration Baseline

_Captured: 2026-05-13, before applying `009_gtfs_composite_keys.sql`._

This file records the dev DB state before the foundation fix lands so
post-migration / post-ETL state can be diffed against it.

## Row counts

| Table | Rows |
|---|---:|
| agencies | 47 |
| gtfs_routes | 349 |
| gtfs_stops | 17,303 |
| gtfs_trips | 84,680 |
| gtfs_stop_times | 3,203,203 |
| gtfs_shapes | 1,602,468 |
| gtfs_shape_geoms | 2,356 |
| gtfs_pathways | 0 |
| gtfs_levels | 0 |
| stop_features | 17,303 |
| stop_safety_scores | 17,303 |
| stop_ada_gap | 17,303 |
| coverage_cells | 2,350 |
| census_tracts | 1,772 |
| census_ambulatory | 1,772 |
| ops_trip_events | 304,421 |
| rt_vehicle_positions_raw | 381,806 |

## Cross-agency corruption (the bug we're fixing)

| Symptom | Count |
|---|---:|
| Distinct `route_id`s in `gtfs_routes` | 347 |
| `route_id`s misattributed (gtfs_routes.agency_id ≠ gtfs_trips.agency_id) | **163 (47%)** |
| Trips referencing a misattributed route | **36,765** |
| Shape_ids referenced by trips of an agency that doesn't own the shape row | **18** |
| Stops orphaned by agency_id mismatch | 0 |

## Canonical "broken" symptom — top-5 ADA-gap stops

```
stop 14483 (SF)  Eddy St & Leavenworth St            routes=0  tracts=3
stop 18049 (SF)  Jones St & Ellis St                 routes=0  tracts=3
stop 14867 (SF)  Leavenworth St & O'Farrell St       routes=0  tracts=3
stop 14480 (SF)  Eddy St & Jones St                  routes=0  tracts=3
stop 15814 (SF)  O'Farrell St & Leavenworth St       routes=1  tracts=3
```

Endpoint: `GET /accessibility/gaps/stops/{stop_id}/breakdown`.
Post-fix expected outcome: **all 5 stops show `routes ≥ 1`**.

## Sprint 5c acceptance status

`scripts/sprint-5c-acceptance.py` currently reports **18/18 PASS** —
but check #9 hides the defect by sampling 5 stops and passing on the
first hit. The plan's Phase 3 Task 6 Step 4 tightens this to require
ALL top-5 to pass.

## Schema dump

Pre-migration schema-only `pg_dump` lives at `/tmp/batis-schema-pre-009.sql`
(2,109 lines). Captured locally for the duration of the migration sprint.
Not checked into git (transient).

## Single-column PKs being replaced

```
gtfs_routes_pkey       PRIMARY KEY (route_id)
gtfs_trips_pkey        PRIMARY KEY (trip_id)
gtfs_stop_times_pkey   PRIMARY KEY (trip_id, stop_sequence)
gtfs_shapes_pkey       PRIMARY KEY (shape_id, shape_pt_sequence)
gtfs_shape_geoms_pkey  PRIMARY KEY (shape_id)
gtfs_stops_pkey        PRIMARY KEY (stop_id)   ← retained, with new composite UNIQUE
```

## FKs to be dropped + re-added

| From | To | Constraint |
|---|---|---|
| gtfs_trips | gtfs_routes | gtfs_trips_route_id_fkey |
| gtfs_stop_times | gtfs_trips | gtfs_stop_times_trip_id_fkey |
| gtfs_stop_times | gtfs_stops | gtfs_stop_times_stop_id_fkey |
| stop_safety_scores | gtfs_stops | stop_safety_scores_stop_id_fkey |
| stop_features | gtfs_stops | stop_features_stop_id_fkey |
