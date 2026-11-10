"""API keys must never reach logs or stored loader results."""
from app.services.gtfs_static_loader import _redact_secrets


def test_api_key_redacted_in_http_error_text():
    msg = ("404 Client Error: Not Found for url: "
           "https://api.511.org/transit/datafeeds?api_key=abc-123&operator_id=CR")
    out = _redact_secrets(msg)
    assert "abc-123" not in out
    assert "api_key=***" in out
    assert "operator_id=CR" in out  # non-secret params stay readable


def test_token_param_redacted():
    assert "SECRET" not in _redact_secrets("GET /x?token=SECRET")


def test_install_redaction_scrubs_stdout_and_logging(capsys):
    import logging
    import sys
    from app.core.redact import install_redaction
    install_redaction()
    print("failed url: https://api.511.org/x?operator_id=CR&api_key=SUPERSECRET")
    logging.getLogger("t").warning("bad %s", "https://x/y?token=TOPSECRET")
    sys.stdout.flush()
    out = capsys.readouterr()
    assert "SUPERSECRET" not in out.out + out.err
    assert "TOPSECRET" not in out.out + out.err
