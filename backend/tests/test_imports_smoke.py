"""Smoke test: every importable app/ml module must import without error.

Guards against missing entries in requirements.txt (e.g. sentence-transformers
or httpx not declared, causing ImportError at server startup).
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from typing import Iterator


_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _iter_module_names(package_root: str, package_name: str) -> Iterator[str]:
    """Yield dotted module names under package_root/package_name."""
    pkg_path = os.path.join(package_root, package_name)
    for _, modname, _ in pkgutil.walk_packages(
        [pkg_path], prefix=f"{package_name}."
    ):
        yield modname


def test_app_modules_import_cleanly():
    """Every module under app.* must import — proves requirements.txt is complete."""
    failures: list[tuple[str, str]] = []
    for modname in _iter_module_names(_BACKEND_ROOT, "app"):
        try:
            importlib.import_module(modname)
        except ImportError as exc:
            failures.append((modname, repr(exc)))

    assert not failures, (
        "ImportError in app modules — likely a missing dependency in "
        "requirements.txt:\n  " + "\n  ".join(f"{m}: {e}" for m, e in failures)
    )


def test_ml_modules_import_cleanly():
    """Every module under ml.* must import — guards the AI pipeline deps."""
    failures: list[tuple[str, str]] = []
    for modname in _iter_module_names(_BACKEND_ROOT, "ml"):
        try:
            importlib.import_module(modname)
        except ImportError as exc:
            failures.append((modname, repr(exc)))

    assert not failures, (
        "ImportError in ml modules — likely sentence-transformers or another "
        "AI dep missing from requirements.txt:\n  "
        + "\n  ".join(f"{m}: {e}" for m, e in failures)
    )
