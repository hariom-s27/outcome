"""Schemathesis against the frozen contract/openapi.yaml, in-process (P1-15)."""

from __future__ import annotations

import pytest
import schemathesis
from conftest import ROOT
from hypothesis import HealthCheck, settings

from app.api import create_app
from app.config import Settings


@pytest.fixture
def api_schema(database_url, clean_db):
    schema = schemathesis.openapi.from_path(ROOT / "contract" / "openapi.yaml")
    # high MAX_PENDING: Schemathesis may create many jobs; 429 is tested in test_api.py
    schema.app = create_app(Settings(database_url=database_url, max_pending=100_000))
    return schema


lazy = schemathesis.pytest.from_fixture("api_schema")


@lazy.parametrize()
@settings(max_examples=40, deadline=None, suppress_health_check=list(HealthCheck))
def test_contract(case):
    # positive_data_acceptance is excluded: openapi.yaml types `schema` as any string and
    # `file` as any bytes, but the same contract documents 400 for "schema not valid JSON"
    # and "unsupported file type". Random strings/bytes are schema-valid yet must get 400.
    # The 400 itself is still checked (status_code_conformance + response schema).
    case.call_and_validate(excluded_checks=[schemathesis.checks.positive_data_acceptance])
