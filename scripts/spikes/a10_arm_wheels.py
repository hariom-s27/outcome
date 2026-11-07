"""A10 (spike 25): does every locked runtime package (plus pdfplumber + pdfminer.six for S2)
have a wheel for linux aarch64 / CPython 3.12?

uv export --no-hashes --no-dev -> one `pip download --only-binary=:all: --no-deps` per package
into cache/spikes/wheels (pip runs via uvx, nothing is added to the project). Windows-only
packages (by environment marker) are skipped. Prints the packages with no aarch64 wheel.
"""

from __future__ import annotations

import re
import subprocess

from _common import OUT_DIR, ROOT, Report

PLATFORMS = ("manylinux2014_aarch64", "manylinux_2_28_aarch64")
EXTRA = ("pdfplumber", "pdfminer.six", "charset-normalizer", "cryptography")  # + their deps
WIN_ONLY = re.compile(r"(sys_platform\s*==\s*['\"]win32|platform_system\s*==\s*['\"]windows)", re.I)


def main() -> None:
    rep = Report("a10_arm_wheels")
    wheels = OUT_DIR / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    exp = subprocess.run(
        ["uv", "export", "--no-hashes", "--no-dev", "--no-emit-project", "--frozen"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )  # fmt: skip
    reqs, skipped = [], []
    for line in exp.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        spec, _, marker = line.partition(";")
        (skipped if WIN_ONLY.search(marker) else reqs).append(spec.strip())
    reqs += list(EXTRA)
    missing = []
    for spec in reqs:
        cmd = ["uvx", "--from", "pip", "pip", "download", "--only-binary=:all:", "--no-deps"]
        for p in PLATFORMS:
            cmd += ["--platform", p]
        cmd += ["--python-version", "3.12", "-d", str(wheels), "-q", spec]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        ok = r.returncode == 0
        rep.line(f"{spec}: {'ok' if ok else 'NO aarch64 wheel'}")
        if not ok:
            missing.append(spec)
            rep.line("  " + (r.stderr.strip().splitlines() or ["?"])[-1])
    files = sorted(p.name for p in wheels.glob("*.whl"))
    pure = sum(1 for f in files if f.endswith("-none-any.whl"))
    rep.sum(
        f"packages checked={len(reqs)} (incl. {', '.join(EXTRA)}) skipped windows-only="
        f"{len(skipped)}; wheels={len(files)} (pure python {pure}, "
        f"aarch64 binary {len(files) - pure})"
    )
    rep.sum(f"no aarch64 wheel: {', '.join(missing) or 'none'}")
    for extra in EXTRA:
        stem = extra.replace(".", "_").replace("-", "_").lower()
        hit = [f for f in files if f.lower().startswith(stem + "-")]
        name = hit[0].rsplit("-", 3) if hit else None
        rep.sum(f"{extra}: {name[0] + ' ' + name[-1] if name else 'missing'}")
    rep.close()


if __name__ == "__main__":
    main()
