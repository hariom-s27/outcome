"""Structure probe: DEV doc ids, file types, schema names, and the KEY NAMES of answer records
(no values). Lets the other spikes read answers the right way."""

from __future__ import annotations

from collections import Counter

from _common import Report, dev_docs, dev_row, truth, truth_entries


def main() -> None:
    rep = Report("probe_shapes")
    for d in dev_docs():
        row = dev_row(d)
        entries = truth_entries(truth(d))
        rec_keys: Counter = Counter()
        for e in entries:
            for v in e.values():
                if isinstance(v, dict):
                    rec_keys.update(v.keys())
        rep.sum(
            f"{d}: file={row['file'].rsplit('.', 1)[-1]} schema={row['schema_name']} "
            f"entries={len(entries)} field_record_keys={sorted(rec_keys)}"
        )
    rep.close()


if __name__ == "__main__":
    main()
