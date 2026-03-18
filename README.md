Bay Area Transit Intelligence
=============================

This project is a prototype **Bay Area Transit Intelligence System** for AC Transit and the City of Oakland.
It ingests AC Transit GTFS static and realtime data into a Supabase (Postgres + PostGIS) backend, exposes
analysis APIs via FastAPI, and renders a React + Mapbox dashboard.

## Structure

- `backend/` – Python services, FastAPI app, ETL workers, and SQL schema for Supabase/PostGIS.
- `frontend/` – React + Mapbox GL JS dashboard application.

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm or pnpm/yarn
- A Supabase project (or any PostgreSQL instance) with the `postgis` extension enabled
- AC Transit API key and/or GTFS / GTFS-Realtime URLs

## Environment

Copy `.env.example` to `.env` (backend) and fill in the values:

- `DATABASE_URL` – Supabase Postgres connection string (service role or equivalent).
- `ACTRANSIT_API_KEY` – AC Transit API token (do not commit this).
- `GTFS_STATIC_URL` – AC Transit GTFS ZIP URL.
- `GTFS_RT_VEHICLE_POSITIONS_URL` – GTFS-Realtime vehicle positions feed URL.
- `GTFS_RT_TRIP_UPDATES_URL` – GTFS-Realtime trip updates feed URL.
- `MAPBOX_ACCESS_TOKEN` – Mapbox token for the frontend.

## Supabase / PostGIS schema

The SQL schema for Supabase/PostGIS lives under `backend/sql/schema.sql`. Apply it to your Supabase
project (or another Postgres database) using the Supabase SQL editor or `psql`.

## Running the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Running the frontend

```bash
cd frontend
npm install
npm run dev
```

