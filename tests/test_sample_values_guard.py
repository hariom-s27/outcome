"""Tests for scripts/guards/sample_values.py (stdlib unittest; also collected by pytest).

All data is invented: fake field keys, fake answer strings and numbers, temp files only.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

GUARDS = Path(__file__).resolve().parents[1] / "scripts" / "guards"
sys.path.insert(0, str(GUARDS))
import sample_values  # noqa: E402

FIELD_KEYS = {"widget_batch_code", "widget_owner"}
# answer text (lowercased) -> field it came from; one answer equals a field key
STRINGS = {"widget_batch_code": "line_label", "zephyrine quarry lot": "widget_owner"}
NUMBERS = {"987654": "widget_count"}


class SampleValuesScan(unittest.TestCase):
    def setUp(self) -> None:
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        Path("outputs").mkdir()

    def tearDown(self) -> None:
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def _scan(self, name: str, text: str) -> list[str]:
        Path(name).write_text(text, encoding="utf-8")
        return sample_values.scan([name], STRINGS, NUMBERS, FIELD_KEYS)

    def test_field_name_match_is_ignored(self) -> None:
        self.assertEqual(self._scan("notes.md", '"widget_batch_code": null\n'), [])

    def test_field_name_with_other_case_is_still_flagged(self) -> None:
        problems = self._scan("notes.md", "WIDGET_BATCH_CODE\n")
        self.assertEqual(problems, ["notes.md:1: matches an answer value for field 'line_label'"])

    def test_real_value_outside_outputs_is_flagged(self) -> None:
        problems = self._scan("notes.md", "ok\nowner is Zephyrine Quarry Lot\ncount 987654\n")
        self.assertEqual(
            problems,
            [
                "notes.md:2: matches an answer value for field 'widget_owner'",
                "notes.md:3: matches an answer value for field 'widget_count'",
            ],
        )
        self.assertFalse(any("zephyrine" in p.lower() or "987" in p for p in problems))

    def test_same_value_inside_outputs_is_not_flagged(self) -> None:
        text = '{"widget_owner": {"value": "Zephyrine Quarry Lot"}, "n": 987654}\n'
        self.assertEqual(self._scan("outputs/doc_x.json", text), [])
        self.assertEqual(self._scan("./outputs/doc_y.json", text), [])

    def test_field_keys_loaded_from_schemas(self) -> None:
        schemas = Path("schemas")
        schemas.mkdir()
        (schemas / "s.json").write_text(
            json.dumps({"name": "s", "fields": {"widget_batch_code": {}, "widget_owner": {}}}),
            encoding="utf-8",
        )
        (schemas / "broken.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(sample_values.load_field_keys(schemas), FIELD_KEYS)

    def test_missing_schema_dir_gives_no_exemptions(self) -> None:
        self.assertEqual(sample_values.load_field_keys(Path("no_such_dir")), set())


if __name__ == "__main__":
    unittest.main()
