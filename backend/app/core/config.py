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

    # Census TIGERweb — authoritative tract polygon REST service
    tigerweb_base_url: str = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/3/query"

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

    # AI / RAG
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    embed_model_name: str = "all-MiniLM-L6-v2"

    # CORS
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

