from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:password@localhost:5432/bay_area_transit_intel"
    actransit_api_key: str | None = None
    gtfs_static_url: str = "https://opendata.actransit.org/transitdata/google_transit.zip"
    gtfs_rt_vehicle_positions_url: str | None = None
    gtfs_rt_trip_updates_url: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

