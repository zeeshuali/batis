from app.core.config import get_settings
from app.services.five11_rt_ingestor import run_polling_loop


def main() -> None:
    from app.core.redact import install_redaction
    install_redaction()
    run_polling_loop(poll_interval_seconds=get_settings().five11_rt_poll_seconds)


if __name__ == "__main__":
    main()
