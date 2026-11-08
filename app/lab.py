"""P9b lab switches (Z-29): which model a single-value job uses.

- SV_MODEL (Settings.sv_model): the model for single-value field lists; None = the YAML
  `baseline` (v1.0). Table field lists always keep the baseline.
- debug_model: a POST /jobs form part, honoured ONLY when LAB_MODE=1. The API stores it in the
  job's field list under LAB_MODEL_KEY; the worker takes it out again before any pipeline sees
  the field list. With LAB_MODE off the API ignores the part and the worker ignores the key,
  so the shipped behaviour is v1.0's exactly.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.extract.compile_fields import is_single_value
from app.llm.models import ALLOWED_MODEL_IDS

LAB_MODEL_KEY = "_lab_model"


class BadDebugModel(ValueError):
    """debug_model names a model outside the brief's list."""


def attach_debug_model(settings: Settings, field_list: dict[str, Any], raw: Any) -> dict[str, Any]:
    """API side: the field list to store. Unchanged unless LAB_MODE is on and a model is given."""
    if not settings.lab_mode or raw is None:
        return field_list
    model = raw.strip() if isinstance(raw, str) else None
    if not model:
        return field_list
    if model not in ALLOWED_MODEL_IDS:
        raise BadDebugModel("debug_model must be one of the allowed model ids")
    return {**field_list, LAB_MODEL_KEY: model}


def split_debug_model(
    settings: Settings, field_list: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Worker side: (field list for the pipelines, debug model or None). LAB_MODE off: the
    field list is returned as stored (v1.0) and no debug model is used."""
    if not settings.lab_mode or LAB_MODEL_KEY not in field_list:
        return field_list, None
    rest = {k: v for k, v in field_list.items() if k != LAB_MODEL_KEY}
    model = field_list[LAB_MODEL_KEY]
    return rest, model if model in ALLOWED_MODEL_IDS else None


def sv_model_for(settings: Settings, field_list: dict[str, Any], debug: str | None) -> str | None:
    """The model override for this job, or None (= the pipeline's own default, v1.0)."""
    if not is_single_value(field_list):
        return None
    return debug or settings.sv_model
