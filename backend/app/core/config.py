from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:password@localhost:5432/bay_area_transit_intel"

    # AC Transit direct GTFS-RT (legacy — being replaced by 511.org)
    actransit_api_key: str | None = None
    gtfs_static_url: str = "https://opendata.actransit.org/transitdata/google_transit.zip"
    gtfs_rt_vehicle_positions_url: str | None = None
    gtfs_rt_trip_updates_url: str | None = None

    # 511.org regional API
    # The list of agencies to ingest now lives in the `agencies` table
    # (populated by five11_operators.run_operators_sync) — see Phase A-1.
    five11_api_key: str | None = None
    five11_base_url: str = "https://api.511.org"
    # RT poll interval. Each cycle makes 2 requests (vehicles + trip updates) and the
    # 511 limit is 60 req/hour shared with other jobs, so keep this >= 120.
    five11_rt_poll_seconds: int = 180

    # 511 allows 60 requests per rolling hour. The status dashboard shows usage against it.
    five11_rate_limit_per_hour: int = 60
    # Status dashboard: run-log retention, and thresholds that turn a status amber/red.
    run_log_retention_days: int = 14
    status_rt_stale_minutes: int = 15
    status_job_stale_minutes: int = 120

    # Daily stop_observations backfill (cron): load this many missing months per run,
    # newest first, never older than max_months_back. Raise these to deepen history.
    stop_obs_backfill_months_per_run: int = 2
    stop_obs_backfill_max_months_back: int = 12

    # Cross-agency transfers are matched spatially. Links are stored up to the largest
    # radius and the user picks one (<= max) at read time.
    transfer_radii_m: list[int] = [50, 100, 150, 200, 300, 400]
    transfer_default_radius_m: int = 150
    transfer_walk_speed_mps: float = 1.2

    # Census TIGERweb — authoritative tract polygon REST service
    tigerweb_base_url: str = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/0/query"

    # Backend API key (X-API-Key header for protected endpoints)
    backend_api_key: str | None = None

    # Census API key — required by api.census.gov as of ~2024.  Get one
    # free at https://api.census.gov/data/key_signup.html.  Without it the
    # equity loader can't refresh median_household_income (Sprint 5a) or
    # the existing equity_score (Sprint 0).
    census_api_key: str | None = None

    # Census ACS 5-year estimates REST base URL.
    census_acs5_base_url: str = "https://api.census.gov/data/2022/acs/acs5"

    # Service delivery gap — tolerance window for "on time".
    # An observed arrival within ±N seconds of scheduled counts as a hit;
    # everything else counts as missed.  Default 300 (=±5 min).
    delivery_gap_tolerance_seconds: int = 300

    ada_catchment_radius_m:       int   = 400
    ada_tier_percentile_high:     float = 0.90
    ada_tier_percentile_moderate: float = 0.75
    ada_tier_percentile_low:      float = 0.50

    # AI / RAG
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    embed_model_name: str = "all-MiniLM-L6-v2"

    # CORS
    # Where the dashboard UI is served (used in the API root message).
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"

    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

