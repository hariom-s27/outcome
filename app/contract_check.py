"""The frozen validator's contract check (tools/validate.py), used on every result we build.

The file is copied into the image unchanged (Dockerfile) and imported by path, so the service
checks itself with exactly the code the graders run.
"""

from __future__ import annotations

import importlib.util
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

VALIDATOR_PATH = Path(__file__).resolve().parent.parent / "tools" / "validate.py"


@cache
def validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("contract_validate", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the contract validator from {VALIDATOR_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def contract_errors(result: dict[str, Any], field_list: dict[str, Any]) -> list[str]:
    """Error strings from validate_contract (field names and positions only, no values
    except currency-formatted strings, which our own checks convert before this runs)."""
    return validator().validate_contract(result, field_list)
