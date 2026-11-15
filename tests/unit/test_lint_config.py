"""Bandit's rules stay on for the shipped code (v1.0b1 D9)."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_bandit_rules_stay_on_and_only_tests_skip_them_all() -> None:
    lint = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["ruff"]["lint"]
    assert "S" in lint["select"]
    ignores = lint["per-file-ignores"]
    assert ignores["tests/**"] == ["S"]
    assert all(codes != ["S"] for path, codes in ignores.items() if path != "tests/**")
