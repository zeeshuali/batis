from app.services.gtfs_rt_ingestor import run_polling_loop


def main() -> None:
    from app.core.redact import install_redaction
    install_redaction()
    # Default 30s polling interval; can be overridden via process manager/CLI if needed.
    run_polling_loop(poll_interval_seconds=30)


if __name__ == "__main__":
    main()

