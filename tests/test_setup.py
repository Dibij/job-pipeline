"""Verification test for project setup and dependencies."""
import importlib
import pytest


def test_core_dependencies():
    """Verify all required libraries are importable."""
    packages = ["pydantic", "psycopg", "requests", "bs4", "dotenv", "tabulate"]
    for pkg in packages:
        module = importlib.import_module(pkg)
        assert module is not None, f"Failed to import {pkg}"


def test_src_imports():
    """Verify internal package modules can be imported."""
    from src import config

    assert config.POSTGRES_DB == "job_pipeline"
    assert config.POSTGRES_PORT == 5432
    assert "postgresql://" in config.DATABASE_URL
