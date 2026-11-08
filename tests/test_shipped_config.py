"""Shipped-config test (P8a A-14, W-1): the graders' `docker compose up` gets no dev settings.

Reads compose.yaml, resolves `${VAR:-default}` as an empty shell would, and feeds the result to
the real settings classes. No Docker, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.llm.settings import LLMSettings

ROOT = Path(__file__).resolve().parent.parent
VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::?-([^}]*))?\}")
DEV_ONLY = (
    "DEV_BUDGET_USD",
    "LLM_CACHE_DIR",
    "LLM_CACHE_MODE",
    "LLM_REASONING_OVERRIDE",
    "SV_MODEL",  # P9b: lab only; shipped = the YAML baseline model
    "LAB_MODE",  # P9b: lab only; shipped = no per-job debug_model
)


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))


def _env(service: dict) -> dict[str, str]:
    env = service.get("environment") or {}
    assert isinstance(env, dict), "environment must be a mapping"
    return {k: str(v) for k, v in env.items()}


def _resolve_empty_shell(env: dict[str, str]) -> dict[str, str]:
    return {k: VAR_RE.sub(lambda m: m.group(2) or "", v) for k, v in env.items()}


def test_no_env_file_anywhere(compose):
    for name, svc in compose["services"].items():
        assert "env_file" not in svc, f"{name} has env_file"


def test_no_platform_pin(compose):
    for name, svc in compose["services"].items():
        assert "platform" not in svc, f"{name} pins a platform"


def test_llm_vars_use_empty_default_form(compose):
    env = _env(compose["services"]["worker"])
    assert env["LLM_BASE_URL"] == "${LLM_BASE_URL:-}"
    assert env["LLM_API_KEY"] == "${LLM_API_KEY:-}"
    assert "LLM_API_KEY" not in _env(compose["services"]["api"])


def test_dev_settings_absent(compose):
    for name, svc in compose["services"].items():
        env = _env(svc)
        for var in DEV_ONLY:
            assert var not in env, f"{name} sets dev-only {var}"
        for vol in svc.get("volumes") or []:
            assert "cache" not in str(vol), f"{name} mounts a cache volume"


def test_single_value_path_defaults_to_baseline(compose):
    env = _env(compose["services"]["worker"])
    assert env["EXTRACT_SINGLE_VALUE_PATH"] == "${EXTRACT_SINGLE_VALUE_PATH:-baseline}"


def test_table_path_defaults_to_spec(compose):
    # P8b: shipped = the table recipe (T-16b passed with the live floor, Z-5)
    env = _env(compose["services"]["worker"])
    assert env["EXTRACT_TABLE_PATH"] == "${EXTRACT_TABLE_PATH:-spec}"


def test_scan_page_method_defaults_to_all(compose):
    # P9e Z-56: lab default = every scan page (gate passed, runs 171-173; full set run 174);
    # SCAN_PAGE_METHOD=first = the v1.0 first 8 pages
    env = _env(compose["services"]["worker"])
    assert env["SCAN_PAGE_METHOD"] == "${SCAN_PAGE_METHOD:-all}"


def test_e0_robust_defaults_to_on(compose):
    # P9b Z-35: shipped = robust parsing on (gate passed, runs 105-106); 0 turns it off
    env = _env(compose["services"]["worker"])
    assert env["E0_ROBUST"] == "${E0_ROBUST:-1}"


def test_pdf_table_method_defaults_to_grid(compose):
    # P9c: shipped = the line grid (gate passed with Z-50, runs 141-143; full set run 144)
    env = _env(compose["services"]["worker"])
    assert env["PDF_TABLE_METHOD"] == "${PDF_TABLE_METHOD:-grid}"


def test_table_cleanup_defaults_to_on(compose):
    # P9c Z-60: shipped = cleanup rules on (cleared on runs 154-157, 161-166)
    env = _env(compose["services"]["worker"])
    assert env["TABLE_CLEANUP"] == "${TABLE_CLEANUP:-1}"


def test_spec_retry_feedback_defaults_to_off(compose):
    # P9g Z-61: off until the Z-62 gate passes; 1 turns it on
    env = _env(compose["services"]["worker"])
    assert env["SPEC_RETRY_FEEDBACK"] == "${SPEC_RETRY_FEEDBACK:-0}"


def test_two_worker_replicas_by_default(compose):
    assert compose["services"]["worker"]["deploy"]["replicas"] == 2


def test_settings_from_shipped_env(compose, monkeypatch):
    for var in (
        *DEV_ONLY,
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "EXTRACT_SINGLE_VALUE_PATH",
        "EXTRACT_TABLE_PATH",
        "SCAN_PAGE_METHOD",
        "E0_ROBUST",
        "PDF_TABLE_METHOD",
        "TABLE_CLEANUP",
        "SPEC_RETRY_FEEDBACK",
    ):
        monkeypatch.delenv(var, raising=False)
    for k, v in _resolve_empty_shell(_env(compose["services"]["worker"])).items():
        monkeypatch.setenv(k, v)
    llm = LLMSettings.from_env()
    assert llm.dev_budget_usd is None
    assert llm.cache_dir is None  # no cache dir -> the disk cache is off
    assert llm.reasoning_override is None
    assert llm.api_key == ""
    assert Settings.from_env().single_value_path == "baseline"
    assert Settings.from_env().table_path == "spec"
    assert Settings.from_env().scan_page_method == "all"
    # P9b: the model switch is off in the shipped config
    assert Settings.from_env().sv_model is None
    assert Settings.from_env().lab_mode is False
    assert Settings.from_env().e0_robust is True  # Z-35: E0 on in the shipped config
    assert Settings.from_env().pdf_table_method == "grid"  # P9c: grid on (gate passed)
    assert Settings.from_env().table_cleanup is True  # P9c Z-60: cleared, default on
    assert Settings.from_env().spec_retry_feedback is False  # P9g: off until Z-62 passes
