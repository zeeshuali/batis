# BATIS — Planned Features

## High Value, Moderate Effort

### 1. Trip Planner ✳️ in progress
Point-to-point routing using GTFS stop_times + shapes, showing real scheduled
departure times with current delay predictions overlaid.

### 2. Isochrone Map
Click any point on the map and visualize how far you can travel by transit in
15 / 30 / 45 minutes (PostGIS + walking distance buffers).

### 3. Accessibility Score per Stop
Combine shelter presence, lighting, sidewalk connectivity, and wheelchair ramp
data into a composite ADA accessibility rating per stop.

### 4. Transfer Heatmap
Identify stops where passengers most commonly transfer between routes, and flag
ones with poor headway alignment (long transfer waits).

---

## Operational / Real-time

- **On-time Prediction** — use current vehicle positions + historical delay patterns
  to predict whether each in-service trip will arrive on time at downstream stops.
- **Service Alerts Feed** — consume the AC Transit GTFS-RT alerts endpoint and
  surface detours, cancellations, and stop closures on the map.
- **Headway Deviation Tracker** — real-time view of actual vs. scheduled headways
  per route, flagging routes currently bunching right now.

---

## Analytical / Dashboard

- **Equity Analysis Panel** — overlay Census tract demographics against transit
  coverage to identify underserved communities.
- **Schedule Adherence Heatmap by Time of Day** — worst hours/days per route.
- **Stop-level Dwell Time Analysis** — stops causing the most delay through long
  dwell times.

---

## User-facing

- **Favorite Stops** — pin stops; show next departures + delay status on load.
- **CSV / PDF Report Export** — summary report for any route or date range.
