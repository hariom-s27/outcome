"""P4 spike harness, shared parts (P4-07, P4-12, P4-13). Measure only (P4-14).

Paid runs happen INSIDE the dev worker container (real LLMClient wrapper, fuses, ledger, env
from compose; the key is never visible), started by scripts/spikes/p4_launch.py after the
clean-tree and dry-run gates. --dry-run runs anywhere (host is fine): it builds every request,
records estimated tokens / images / $ and makes no call (no DB, no key, no network).

Outputs under <spikes>/<run_id>/ (host: cache/spikes/, container: /spikes, git-ignored):
  <doc>__<variant>.json   job-shaped prediction ({"status", "result": {entries, metadata}})
                          for scripts/spikes/p4_score.py (host-side scoring, answers never
                          mounted into a container)
  calls.jsonl             one line per call: model requested/returned, JSON mode sent, repair,
                          tokens in/out/reasoning, images, latency, $ reported vs computed
  summary.json            spent, caps, stop reason
Printed: <= 15 summary lines; counts, tokens, $ and field names only (D04, R23).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import re
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.contract_check import validator  # noqa: E402
from app.llm.models import ModelCatalog, ModelSpec  # noqa: E402
from app.pipeline import baseline  # noqa: E402
from app.readers import Block, read_document  # noqa: E402

HELD_OUT = frozenset({"lease_003", "budget_001"})  # D03 / P4-16: never opened, run or scored
TOKEN_LIMIT = 90_000  # R22: every request well under Haiku's 100k price cliff
MAX_IMAGES = 8  # R13
OUT_PROJECTION = 3_000  # output tokens assumed by the --max-usd stop before a call
CONTAINER = Path("/srv/devdocs").is_dir()

B1_MODELS = (
    "anthropic/claude-haiku-5.5",
    "openai/gpt-6-luna",
    "z-ai/glm-5.3-flash",
    "qwen/qwen3-vl-235b-a22b-instruct",
    "google/gemini-3.8-flash",
)
HAIKU = "anthropic/claude-haiku-5.5"
PAGE_RE = re.compile(r"\[\s*page\s+(\d+)", re.IGNORECASE)


# --- paths ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Paths:
    docs: Path
    schemas: Path
    manifest: Path
    spikes: Path

    @classmethod
    def detect(cls) -> Paths:
        if CONTAINER:  # mounts made by p4_launch.py
            return cls(
                Path("/srv/devdocs"), Path("/srv/schemas"), Path("/srv/manifest.csv"),
                Path("/spikes"),
            )  # fmt: skip
        sample = ROOT / "sample"
        return cls(
            sample / "sample-data-documents", sample / "schemas", sample / "manifest.csv",
            ROOT / "cache" / "spikes",
        )  # fmt: skip


def manifest(paths: Paths) -> dict[str, dict[str, str]]:
    with paths.manifest.open(newline="", encoding="utf-8") as f:
        return {row["document_id"]: row for row in csv.DictReader(f)}


@dataclass
class Doc:
    doc_id: str
    file_type: str
    field_list: dict[str, Any]
    blocks: list[Block]


def load_doc(doc_id: str, paths: Paths) -> Doc:
    if doc_id in HELD_OUT:
        raise SystemExit("refused: held-out document (P4-16)")
    row = manifest(paths)[doc_id]
    path = paths.docs / row["file"]
    file_type = path.suffix.lower().lstrip(".")
    field_list = json.loads((paths.schemas / f"{row['schema_name']}.json").read_text("utf-8"))
    dm = read_document(file_type, path.read_bytes())
    return Doc(doc_id, file_type, field_list, dm.blocks)


# --- pure helpers (unit-tested on invented data) ------------------------------------------------


def primary_key(fields: dict[str, Any]) -> str | None:
    return baseline._primary(fields)


def page_batches(blocks: list[Block], size: int = MAX_IMAGES) -> list[list[Block]]:
    """Blocks grouped by page, at most `size` pages per batch, document order kept."""
    pages: list[int | None] = []
    for b in blocks:
        if b.page not in pages:
            pages.append(b.page)
    out = []
    for i in range(0, len(pages), size):
        chosen = set(pages[i : i + size])
        out.append([b for b in blocks if b.page in chosen])
    return out


def batch_pages(batch: list[Block]) -> set[int]:
    return {b.page for b in batch if b.page is not None}


def thumbnail(block: Block, long_side: int = 512) -> Block:
    """A smaller JPEG of an image block (B2 locate pass)."""
    from PIL import Image  # Pillow ships with the reader stack (pypdfium2 to_pil)

    img = Image.open(io.BytesIO(block.jpeg or b""))
    img.thumbnail((long_side, long_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80, optimize=True)
    return replace(block, jpeg=buf.getvalue(), width=img.width, height=img.height)


def split_fields(field_list: dict[str, Any], groups: int = 3) -> list[dict[str, Any]]:
    """Field list -> `groups` field lists in field-list order; the row key goes in every one."""
    fields = field_list["fields"]
    primary = primary_key(fields)
    keys = [k for k in fields if k != primary]
    size = math.ceil(len(keys) / groups) if keys else 0
    out = []
    for i in range(groups):
        part = keys[i * size : (i + 1) * size]
        if not part:
            continue
        sub = {primary: fields[primary]} if primary else {}
        sub.update({k: fields[k] for k in part})
        out.append({**field_list, "fields": sub})
    return out


def _norm(v: Any) -> Any:
    if isinstance(v, list):
        return ("list", tuple(sorted(str(validator().norm(x)) for x in v)))
    return validator().norm(v)


def _is_null(cell: dict[str, Any]) -> bool:
    v = cell.get("value")
    return v is None or v == []


def cited_pages(citation: str) -> set[int]:
    return {int(m) for m in PAGE_RE.findall(citation or "")}


def _pick(cands: list[tuple[dict[str, Any], set[int]]]) -> tuple[dict[str, Any] | None, bool]:
    """Merge rule (B1): non-null wins; equal values -> highest confidence; different values ->
    the one whose citation names a page that was in its own batch, if exactly one value has
    that; else null and a conflict. Returns (cell or None for null, conflict)."""
    live = [(c, p) for c, p in cands if not _is_null(c)]
    if not live:
        return None, False
    values = {_norm(c["value"]) for c, _ in live}
    if len(values) == 1:
        return max((c for c, _ in live), key=lambda c: c.get("confidence", 0)), False
    grounded = [(c, p) for c, p in live if cited_pages(c.get("citation", "")) & p]
    gvalues = {_norm(c["value"]) for c, _ in grounded}
    if len(gvalues) == 1:
        return max((c for c, _ in grounded), key=lambda c: c.get("confidence", 0)), False
    return None, True


NULL_CELL = {"value": None, "citation": "", "confidence": 0.5}


def merge_batches(
    results: list[tuple[list[dict[str, Any]] | None, set[int]]], fields: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Per-batch entries (+ the pages each batch saw) -> merged entries and conflict field
    names. One-entry schemas merge field by field; table schemas merge rows by row key."""
    primary = primary_key(fields)
    conflicts: list[str] = []
    if not primary:
        merged = {}
        for k in fields:
            cands = [(es[0][k], pages) for es, pages in results if es]
            cell, conflict = _pick(cands)
            merged[k] = dict(cell) if cell else dict(NULL_CELL)
            if conflict:
                conflicts.append(k)
        return [merged], conflicts
    rows: dict[Any, list[tuple[dict[str, Any], set[int]]]] = {}
    for es, pages in results:
        for e in es or []:
            rows.setdefault(_norm(e[primary]["value"]), []).append((e, pages))
    out = []
    for group in rows.values():
        merged = {}
        for k in fields:
            cell, conflict = _pick([(e[k], p) for e, p in group])
            merged[k] = dict(cell) if cell else dict(NULL_CELL)
            if conflict:
                conflicts.append(k)
        out.append(merged)
    return out, conflicts


def merge_groups(
    group_entries: list[list[dict[str, Any]] | None], fields: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """B4: entries from field groups -> one entry list over all fields (missing = null)."""
    primary = primary_key(fields)
    if not any(group_entries):
        return None
    if not primary:
        merged = {k: dict(NULL_CELL) for k in fields}
        for es in group_entries:
            for k, cell in ((es or [{}])[0]).items():
                if k in fields:
                    merged[k] = cell
        return [merged]
    rows: dict[Any, dict[str, Any]] = {}
    for es in group_entries:
        for e in es or []:
            row = rows.setdefault(_norm(e[primary]["value"]), {k: dict(NULL_CELL) for k in fields})
            for k, cell in e.items():
                if k in fields and (k != primary or _is_null(row[k])):
                    row[k] = cell
    return list(rows.values())


def realistic_image_tokens(model: str, width: int, height: int) -> int:
    """Rough per-provider image tokens for the plan only (DR11); real counts come from usage."""
    if model.startswith("anthropic/"):
        s = min(1.0, 1568 / max(width, height, 1))
        return min(1600, int(width * s * height * s / 750))
    if model.startswith("google/"):
        return 1120
    if model.startswith("openai/"):
        s = min(1.0, 2048 / max(width, height, 1))
        w, h = width * s, height * s
        s2 = min(1.0, 768 / max(1, min(w, h)))
        tiles = math.ceil(w * s2 / 512) * math.ceil(h * s2 / 512)
        return 85 + 170 * tiles
    return int(width * height / 784)  # 28x28 patches (Qwen-VL / GLM style)


# --- calls --------------------------------------------------------------------------------------


@dataclass
class Budget:
    max_usd: float
    spent_usd: float = 0.0
    stop: str | None = None


@dataclass
class Recorder:
    """Every call (live or dry) -> one calls.jsonl line; totals per variant for metadata."""

    run_dir: Path
    catalog: ModelCatalog
    budget: Budget
    dry: bool
    lines: list[dict[str, Any]] = field(default_factory=list)

    def note(self, line: dict[str, Any]) -> None:
        self.lines.append(line)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with (self.run_dir / "calls.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(line) + "\n")

    def totals(self, doc: str, variant: str) -> dict[str, Any]:
        ls = [x for x in self.lines if x.get("variant") == variant and x.get("doc") == doc]
        cost = sum(x.get("cost_usd") or 0.0 for x in ls)
        return {
            "model_calls": sum(1 for x in ls if x.get("status") == "ok"),
            "tokens_in": sum(x.get("tokens_in") or 0 for x in ls),
            "tokens_out": sum(x.get("tokens_out") or 0 for x in ls),
            "tokens_reasoning": sum(x.get("tokens_reasoning") or 0 for x in ls),
            "cost_usd": round(cost, 6),
            "cost_computed_usd": round(sum(x.get("cost_computed_usd") or 0.0 for x in ls), 6),
            "latency_ms": sum(x.get("latency_ms") or 0 for x in ls),
            "models_returned": sorted({x["model_returned"] for x in ls if x.get("model_returned")}),
            "images_sent": sum(x.get("images") or 0 for x in ls),
            "repair_calls": sum(1 for x in ls if x.get("purpose") == "repair"),
            "est_tokens_in": sum(x.get("est_tokens_in") or 0 for x in ls),
            "est_usd": round(sum(x.get("est_usd") or 0.0 for x in ls), 6),
            "est_usd_realistic": round(sum(x.get("est_usd_realistic") or 0.0 for x in ls), 6),
            "est_calls": len(ls),
        }


def _content_counts(messages: list[dict[str, Any]]) -> tuple[int, int]:
    chars = images = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
            continue
        for part in c or []:
            if part.get("type") == "image_url":
                images += 1
            else:
                chars += len(part.get("text") or "")
    return chars, images


def estimate_line(
    catalog: ModelCatalog,
    spec: ModelSpec,
    messages: list[dict[str, Any]],
    kind_chars: dict[str, int] | None,
    out_tokens: int,
    image_sizes: list[tuple[int, int]],
) -> dict[str, Any]:
    est_in = catalog.estimate.tokens(messages, kind_chars)
    chars, images = _content_counts(messages)
    img_fuse = images * catalog.estimate.image_tokens
    img_real = sum(realistic_image_tokens(spec.id, w, h) for w, h in image_sizes)
    real_in = max(0, est_in - math.ceil(img_fuse * (1 + catalog.estimate.margin))) + img_real
    return {
        "est_tokens_in": est_in,
        "est_tokens_in_realistic": real_in,
        "est_tokens_out": out_tokens,
        "est_usd": round(spec.cost(est_in, out_tokens), 6),
        "est_usd_realistic": round(spec.cost(real_in, out_tokens), 6),
        "text_chars": chars,
        "images": images,
    }


def out_tokens_guess(spec: ModelSpec, n_fields: int, purpose: str) -> int:
    """Plan-only output guess: ~60 tokens per field cell, ~300 for a locate answer, plus
    ~1,500 reasoning tokens when the model reasons by default (GLM mandatory, Gemini low)."""
    base = 300 if purpose == "locate" else 60 * max(1, n_fields)
    reasons = spec.reasoning_param() is None and spec.id.startswith(("z-ai/", "google/"))
    return base + (1_500 if reasons else 0)


class Caller:
    """One JSON call through the real client (live) or an estimate only (dry)."""

    def __init__(self, rec: Recorder, llm: Any = None):
        self.rec, self.llm, self.cat = rec, llm, rec.catalog
        self.doc = ""
        self.variant = ""
        self.n_fields = 0
        self.image_sizes: list[tuple[int, int]] = []
        if llm is not None:
            self._wrap_chat()

    def _wrap_chat(self) -> None:
        from app.llm.client import LLMStopped

        orig = self.llm.chat

        def chat(ctx, model, messages, **kw):
            spec = self.cat.get(model)
            est = estimate_line(
                self.cat, spec, messages, kw.get("kind_chars"),
                min(kw.get("max_tokens") or spec.max_tokens, OUT_PROJECTION), self.image_sizes,
            )  # fmt: skip
            line = {"doc": self.doc, "variant": self.variant, "purpose": ctx.purpose,
                    "model_requested": model,
                    "json_mode_sent": spec.response_format,
                    "reasoning_sent": spec.reasoning_param(self.llm.settings.reasoning_override),
                    **est}  # fmt: skip
            b = self.rec.budget
            if est["est_tokens_in"] >= TOKEN_LIMIT:  # this call only (R22)
                self.rec.note({**line, "status": "skipped_token_limit"})
                raise LLMStopped("spike_token_limit")
            if b.spent_usd + est["est_usd"] > b.max_usd:
                b.stop = b.stop or "max_usd"  # the whole run stops: partial is reported
            if b.stop:
                self.rec.note({**line, "status": f"skipped_{b.stop}"})
                raise LLMStopped(f"spike_{b.stop}")
            t0 = time.monotonic()
            try:
                res = orig(ctx, model, messages, **kw)
            except Exception as exc:  # recorded, then re-raised for the JSON ladder to map
                self.rec.note({**line, "status": type(exc).__name__,
                               "detail": str(getattr(exc, "reason", ""))[:80],
                               "latency_ms": int((time.monotonic() - t0) * 1000)})  # fmt: skip
                raise
            u = res.usage or {}
            t_in, t_out = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
            rep = u.get("cost")
            computed = spec.cost(t_in, t_out)
            paid = (
                0.0 if res.cache_hit else (float(rep) if isinstance(rep, int | float) else computed)
            )
            b.spent_usd += paid
            self.rec.note({
                **line, "status": "ok", "model_returned": res.model_returned,
                "model_mismatch": res.model_mismatch, "finish_reason": res.finish_reason,
                "cache_hit": res.cache_hit, "tokens_in": t_in, "tokens_out": t_out,
                "tokens_reasoning": (u.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens"),
                "tokens_cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                "cost_reported_usd": rep if isinstance(rep, int | float) else None,
                "cost_computed_usd": round(computed, 6), "cost_usd": round(paid, 6),
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "image_tokens_per_image_est": (
                    round((t_in - est["text_chars"] / 3.0) / est["images"])
                    if est["images"] else None),
            })  # fmt: skip
            return res

        self.llm.chat = chat

    def ctx(self, purpose: str = "extract", job: bool = False):
        from app.llm import CallContext

        # job=True: a fresh job id so the worker's per-doc $ fuse applies (baseline as shipped)
        return CallContext(str(uuid.uuid4()) if job else None, time.time() + 900, purpose)

    def json(
        self,
        model: str,
        messages: list[dict[str, Any]],
        kind_chars: dict[str, int] | None = None,
        purpose: str = "extract",
    ) -> Any:
        """-> parsed JSON dict, or None (failed / stopped / dry)."""
        if self.llm is None:
            spec = self.cat.get(model)
            out = out_tokens_guess(spec, self.n_fields, purpose)
            est = estimate_line(self.cat, spec, messages, kind_chars, out, self.image_sizes)
            self.rec.note({"doc": self.doc, "variant": self.variant, "purpose": purpose,
                           "model_requested": model, "status": "dry", **est})  # fmt: skip
            return None
        out = self.llm.complete_json(
            self.ctx(purpose), model, messages, max_tokens=baseline.MAX_TOKENS,
            kind_chars=kind_chars,
        )  # fmt: skip
        return out.data if out.status == "ok" else None


def extract_call(
    caller: Caller, model: str, field_list: dict[str, Any], blocks: list[Block], file_type: str
) -> list[dict[str, Any]] | None:
    """Baseline prompt over these blocks -> checked entries (or None)."""
    messages, notes = baseline.build_messages(
        field_list, blocks, file_type, est=caller.cat.estimate
    )
    kind_chars = notes.pop(baseline.KIND_CHARS, None)
    caller.n_fields = len(field_list["fields"])
    caller.image_sizes = [(b.width, b.height) for b in blocks if b.kind == "image"][:MAX_IMAGES]
    data = caller.json(model, messages, kind_chars)
    if data is None:
        return None
    entries, _ = baseline.check_answer(data, field_list)
    return entries


# --- output -------------------------------------------------------------------------------------


def write_prediction(
    run_dir: Path,
    doc_id: str,
    variant: str,
    entries: list[dict[str, Any]] | None,
    totals: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> None:
    meta = {**totals, "pipeline": f"p4-{variant}", **(extra or {})}
    job: dict[str, Any] = {"status": "SUCCESS" if entries else "FAILED", "variant": variant}
    if entries:
        job["result"] = {"entries": entries, "metadata": meta}
    else:
        job["metadata"] = meta
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{doc_id}__{variant}.json").write_text(
        json.dumps(job, indent=1), encoding="utf-8", newline="\n"
    )


def common_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--max-usd", type=float, required=True, help="hard cap for this run")
    ap.add_argument("--dry-run", action="store_true", help="build requests, estimate, no call")
    ap.add_argument("--no-cache", action="store_true", help="bypass the dev LLM cache")
    ap.add_argument("--run-id", help="set by p4_launch.py (paid runs)")


@dataclass
class Session:
    paths: Paths
    run_dir: Path
    rec: Recorder
    caller: Caller
    llm: Any

    def load(self, doc_id: str) -> Doc:
        doc = load_doc(doc_id, self.paths)
        self.caller.doc = doc.doc_id  # calls.jsonl lines and totals are per (doc, variant)
        return doc

    def write(
        self,
        doc_id: str,
        variant: str,
        entries: list[dict[str, Any]] | None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Prediction file (live runs only) + one printable line (counts and $ only)."""
        t = self.rec.totals(doc_id, variant)
        if not self.rec.dry:
            write_prediction(self.run_dir, doc_id, variant, entries, t, extra)
        conflicts = (extra or {}).get("conflicts")
        return (
            f"{doc_id} {variant}: calls={t['model_calls']} images={t['images_sent']} "
            f"in={t['tokens_in']} out={t['tokens_out']} reasoning={t['tokens_reasoning']} "
            f"$={t['cost_usd']:.5f} est_calls={t['est_calls']} est_in={t['est_tokens_in']} "
            f"est$={t['est_usd']:.5f}/{t['est_usd_realistic']:.5f} "
            f"latency={t['latency_ms']}ms entries={len(entries or [])}"
            + (f" conflicts={conflicts}" if conflicts is not None else "")
        )

    def baseline_variant(self, doc: Doc, variant: str) -> str:
        """The shipped baseline, unchanged (B3, B4 one-call): worker path incl. the per-doc
        fuse (fresh job id). Dry: the same prompt, estimated only."""
        c = self.caller
        c.variant, c.n_fields = variant, len(doc.field_list["fields"])
        c.image_sizes = [(b.width, b.height) for b in doc.blocks if b.kind == "image"][:8]
        if self.llm is None:
            messages, notes = baseline.build_messages(
                doc.field_list, doc.blocks, doc.file_type, est=c.cat.estimate
            )
            c.json(c.cat.baseline, messages, notes.pop(baseline.KIND_CHARS, None))
            return self.write(doc.doc_id, variant, None)
        out = baseline.extract(self.llm, c.ctx(job=True), doc.field_list, doc.blocks, doc.file_type)
        keep = ("truncated", "images_sent", "blocks_sent", "cost_fuse", "json_repaired")
        extra = {k: out.notes[k] for k in keep if k in out.notes} | {"reason": out.reason}
        return self.write(doc.doc_id, variant, out.entries, extra)

    def close(self, spike: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        b = self.rec.budget
        summary = {
            "spike": spike, "run_id": self.run_dir.name, "dry_run": self.rec.dry,
            "max_usd": b.max_usd, "spent_usd": round(b.spent_usd, 6), "stop": b.stop,
            "calls": len(self.rec.lines),
            "est_usd": round(sum(x.get("est_usd") or 0 for x in self.rec.lines), 6),
            "est_usd_realistic": round(
                sum(x.get("est_usd_realistic") or 0 for x in self.rec.lines), 6),
            "est_tokens_in": sum(x.get("est_tokens_in") or 0 for x in self.rec.lines),
            "images": sum(x.get("images") or 0 for x in self.rec.lines),
            **(extra or {}),
        }  # fmt: skip
        (self.run_dir / "summary.json").write_text(json.dumps(summary, indent=1), "utf-8")
        if self.llm is not None:
            self.llm.close()
        return summary


def open_session(spike: str, args: argparse.Namespace) -> Session:
    paths = Paths.detect()
    if not args.dry_run:
        if not CONTAINER:
            raise SystemExit("refused: paid spikes run in the dev worker via p4_launch.py")
        if not args.run_id:
            raise SystemExit("refused: --run-id missing (start paid spikes with p4_launch.py)")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = args.run_id or f"dry-{spike}-{stamp}"
    run_dir = paths.spikes / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    catalog = ModelCatalog.load()
    rec = Recorder(run_dir, catalog, Budget(args.max_usd), dry=args.dry_run)
    llm = None
    if not args.dry_run:
        from app.config import Settings
        from app.llm import LLMClient
        from app.llm.settings import LLMSettings
        from app.llm.store import LLMStore

        settings = LLMSettings.from_env()
        if args.no_cache:
            settings = replace(settings, cache_dir=None)
        llm = LLMClient(settings, catalog, LLMStore(Settings.from_env().database_url))
    return Session(paths, run_dir, rec, Caller(rec, llm), llm)


def print_summary(summary: dict[str, Any]) -> None:
    print(
        f"{summary['spike']} run={summary['run_id']} dry={summary['dry_run']} "
        f"calls={summary['calls']} images={summary['images']} "
        f"est_tokens_in={summary['est_tokens_in']} est$={summary['est_usd']:.4f} "
        f"(realistic {summary['est_usd_realistic']:.4f}) spent$={summary['spent_usd']:.4f} "
        f"cap$={summary['max_usd']} stop={summary['stop']}"
    )
