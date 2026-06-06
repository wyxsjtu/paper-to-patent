#!/usr/bin/env python3
"""Dependency and toolchain check for the patent-disclosure skill."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


PY_MODULES = [
    ("requests", True, "CNIPA/Google patent search"),
    ("bs4", True, "CNIPA HTML parsing"),
    ("fitz", False, "best PDF parsing (PyMuPDF)"),
    ("pdfminer.high_level", False, "PDF parsing fallback"),
    ("docx", False, "DOCX fallback writer"),
    ("playwright.sync_api", False, "backup epub.cnipa.gov.cn browser source"),
]

BINARIES = [
    ("pdftotext", False, "PDF parsing fallback"),
    ("pandoc", False, "best Markdown to DOCX conversion"),
    ("mmdc", False, "local Mermaid to PNG conversion"),
    ("curl", False, "diagnostics / online fallback"),
]

EXTRA_PATHS = [
    os.path.expanduser("~/.npm-global/bin"),
    os.path.expanduser("~/.local/bin"),
]

for _p in EXTRA_PATHS:
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")


def _module_ok(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except Exception as exc:
        return str(exc)
    out = (r.stdout or r.stderr).strip().splitlines()
    return out[0] if out else f"exit={r.returncode}"


def _find_pandoc() -> str:
    path = shutil.which("pandoc")
    if path:
        return path
    try:
        import pypandoc
        candidate = pypandoc.get_pandoc_path()
        if candidate and os.path.isfile(candidate):
            return candidate
    except Exception:
        pass
    return ""


def collect_checks() -> list[Check]:
    checks: list[Check] = []
    for mod, required, purpose in PY_MODULES:
        ok = _module_ok(mod)
        checks.append(Check(
            name=f"python:{mod}",
            ok=ok,
            detail=purpose if ok else f"missing; install for {purpose}",
            required=required,
        ))

    for binary, required, purpose in BINARIES:
        path = _find_pandoc() if binary == "pandoc" else shutil.which(binary)
        detail = f"{path} ({purpose})" if path else f"missing; install for {purpose}"
        checks.append(Check(
            name=f"bin:{binary}",
            ok=bool(path),
            detail=detail,
            required=required,
        ))

    display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    checks.append(Check(
        name="env:display",
        ok=display,
        detail="DISPLAY/WAYLAND_DISPLAY available" if display else "not set; backup epub source will be skipped",
        required=False,
    ))

    pandoc = _find_pandoc()
    if pandoc:
        checks.append(Check("version:pandoc", True, _version([pandoc, "--version"]), False))
    if shutil.which("mmdc"):
        checks.append(Check("version:mmdc", True, _version(["mmdc", "--version"]), False))
    if _module_ok("fitz"):
        import fitz
        checks.append(Check("version:pymupdf", True, getattr(fitz, "__doc__", "").splitlines()[0], False))

    return checks


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Check patent-disclosure dependencies")
    ap.add_argument("--json", action="store_true", help="print JSON report")
    args = ap.parse_args()

    checks = collect_checks()
    required_failed = [c for c in checks if c.required and not c.ok]

    if args.json:
        print(json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=2))
    else:
        print("Patent disclosure skill environment check")
        print("=" * 48)
        for c in checks:
            flag = "OK" if c.ok else ("MISS" if c.required else "WARN")
            print(f"[{flag:4}] {c.name:<28} {c.detail}")
        print("=" * 48)
        if required_failed:
            print("Required dependencies missing:")
            for c in required_failed:
                print(f"  - {c.name}: {c.detail}")
        else:
            print("Required dependencies are available.")
        print("\nRecommended install:")
        print("  python3 -m pip install pymupdf pdfminer.six python-docx playwright")
        print("  python3 -m playwright install chromium")
        print("  conda install -y -c conda-forge pandoc  # or sudo apt install pandoc")
        print("  npm install -g @mermaid-js/mermaid-cli  # optional; mermaid.ink fallback works online")

    return 1 if required_failed else 0


if __name__ == "__main__":
    sys.exit(main())
