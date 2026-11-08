"""Runtime settings, read from the environment once per process."""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.llm.models import ALLOWED_MODEL_IDS

DEFAULT_DATABASE_URL = "postgresql://docextract:docextract@db:5432/docextract"
SINGLE_VALUE_PATHS = ("baseline", "smart")
TABLE_PATHS = ("baseline", "spec")
SCAN_PAGE_METHODS = ("first", "locate", "all")
PDF_TABLE_METHODS = ("single", "grid")
E0_OFF = ("0", "false", "no", "off")  # Z-35: E0_ROBUST values that turn E0 off; unset = on


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    max_pending: int = 500  # P1-10: 429 when PENDING >= this
    max_upload_bytes: int = 50 * 1024 * 1024  # P1-10: 413 above 50 MB
    job_deadline_s: int = 1500  # P1-08: PARTIAL skeleton this long after submission
    lease_s: int = 60  # P1-06; env LEASE_S
    heartbeat_s: float = 15.0  # P1-06; env HEARTBEAT_S (must be < lease)
    max_attempts: int = 3  # poison job: claimed this many times without finishing
    sweep_every_s: float = 5.0  # env SWEEP_EVERY_S
    worker_poll_s: float = 1.0
    fake_work_s: float = 0.0  # dev/chaos only: simulated processing time; never set in compose
    version: str = "dev"
    # P5-03/P5-04: single-value field lists go to the smart path only when "smart";
    # table field lists always keep the baseline. env EXTRACT_SINGLE_VALUE_PATH.
    single_value_path: str = "baseline"
    # P6 T-15: table field lists go to the spec path (XLSX/CSV tables) when "spec"; shipped
    # default since P8b (T-16b passed with the live floor, Z-5). env EXTRACT_TABLE_PATH.
    table_path: str = "spec"
    # P8b Z-13: the baseline single-value path on a scan with more page images than it can
    # send: "first" = the first pages (as before), "locate" = the P5 locator picks them,
    # "all" (P9e Z-53/Z-54) = every page image up to 40, each tagged "PAGE n of N" by code,
    # in the same one call. env SCAN_PAGE_METHOD. P9e: default all on lab (Z-56 gate passed,
    # runs 171-173; must-not-error full set run 174); first = the v1.0 first 8 pages.
    scan_page_method: str = "all"
    # P9b Z-29: the model for single-value field lists; None = config/models.yaml `baseline`
    # (v1.0). Table field lists keep the baseline. env SV_MODEL (lab only, never in compose.yaml).
    sv_model: str | None = None
    # P9b: LAB_MODE=1 lets POST /jobs carry a `debug_model` form part (one job, one model).
    # Off in the shipped config; when off the part is ignored. env LAB_MODE.
    lab_mode: bool = False
    # P9b E0 (Z-33): robust parsing. Single-value: per-field salvage of a broken answer, then
    # one fresh extraction call if still unusable. Table spec: one more spec call when row
    # fill < 0.5 or a spec entry was dropped, higher fill kept. Z-35: default ON (its gate
    # passed, runs 105-106); E0_ROBUST=0 (or false/no/off) turns it off = the v1.0 path.
    e0_robust: bool = True
    # P9c Z-42: table field lists on a text-layer PDF. "single" = the v1.0 call (one baseline
    # answer); "grid" = PDF -> line grid -> virtual sheet -> the spec path, v1.0 call when the
    # grid fails its checks. env PDF_TABLE_METHOD. P9c: default grid on lab (Z-47 gate with
    # Z-50 passed, runs 141-143; must-not-error full set run 144); single = the v1.0 call.
    pdf_table_method: str = "grid"
    # P9c Z-51: two general cleanup rules on code-copied table rows (placeholder cells -> null,
    # "(continued)" off carried section labels). Default on (lab) since Z-60 cleared it (runs
    # 154-157, 161-166); env TABLE_CLEANUP=0 (or false/no/off) turns it off.
    table_cleanup: bool = True
    # P9g Z-61: table spec answers keep an entry with an unknown extra key (the key ignored,
    # counted), and the E0 spec retry is told what failed (key names, allowed keys, unfilled
    # field names). Default off (= the lab path); env SPEC_RETRY_FEEDBACK=1 (or true/yes/on).
    spec_retry_feedback: bool = False

    def __post_init__(self) -> None:
        if self.pdf_table_method not in PDF_TABLE_METHODS:
            raise ValueError(
                f"PDF_TABLE_METHOD must be one of {PDF_TABLE_METHODS}, "
                f"got {self.pdf_table_method!r}"
            )
        if self.sv_model is not None and self.sv_model not in ALLOWED_MODEL_IDS:
            raise ValueError(f"SV_MODEL must be an allowed model id, got {self.sv_model!r}")
        if self.scan_page_method not in SCAN_PAGE_METHODS:
            raise ValueError(
                f"SCAN_PAGE_METHOD must be one of {SCAN_PAGE_METHODS}, "
                f"got {self.scan_page_method!r}"
            )
        if self.single_value_path not in SINGLE_VALUE_PATHS:
            raise ValueError(
                f"EXTRACT_SINGLE_VALUE_PATH must be one of {SINGLE_VALUE_PATHS}, "
                f"got {self.single_value_path!r}"
            )
        if self.table_path not in TABLE_PATHS:
            raise ValueError(
                f"EXTRACT_TABLE_PATH must be one of {TABLE_PATHS}, got {self.table_path!r}"
            )
        if not 0 < self.heartbeat_s < self.lease_s:
            raise ValueError(
                f"need 0 < HEARTBEAT_S < LEASE_S, got {self.heartbeat_s} and {self.lease_s}"
            )
        if self.sweep_every_s <= 0:
            raise ValueError(f"SWEEP_EVERY_S must be > 0, got {self.sweep_every_s}")

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            database_url=env.get("DATABASE_URL") or DEFAULT_DATABASE_URL,
            max_pending=int(env.get("MAX_PENDING") or 500),
            job_deadline_s=int(env.get("JOB_DEADLINE_S") or 1500),
            lease_s=int(env.get("LEASE_S") or 60),
            heartbeat_s=float(env.get("HEARTBEAT_S") or 15.0),
            sweep_every_s=float(env.get("SWEEP_EVERY_S") or 5.0),
            fake_work_s=float(env.get("WORKER_FAKE_WORK_S") or 0.0),
            worker_poll_s=float(env.get("WORKER_POLL_S") or 1.0),
            version=env.get("APP_VERSION") or "dev",
            single_value_path=(env.get("EXTRACT_SINGLE_VALUE_PATH") or "baseline").strip().lower(),
            table_path=(env.get("EXTRACT_TABLE_PATH") or "spec").strip().lower(),
            scan_page_method=(env.get("SCAN_PAGE_METHOD") or "all").strip().lower(),
            sv_model=(env.get("SV_MODEL") or "").strip() or None,
            lab_mode=(env.get("LAB_MODE") or "").strip().lower() in ("1", "true", "yes"),
            e0_robust=(env.get("E0_ROBUST") or "").strip().lower() not in E0_OFF,
            pdf_table_method=(env.get("PDF_TABLE_METHOD") or "grid").strip().lower(),
            table_cleanup=(env.get("TABLE_CLEANUP") or "").strip().lower() not in E0_OFF,
            spec_retry_feedback=(env.get("SPEC_RETRY_FEEDBACK") or "").strip().lower()
            in ("1", "true", "yes", "on"),
        )
