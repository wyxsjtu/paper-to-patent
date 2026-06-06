#!/usr/bin/env python3
"""
Academic paper parser: PDF and LaTeX project directories.

Extracts structured content for patent disclosure writing:
  title, abstract, contributions, methodology, formulas,
  figure captions, experiment results, conclusion.

Usage:
  python3 parse_paper.py /path/to/paper.pdf
  python3 parse_paper.py /path/to/latex_dir/
  python3 parse_paper.py /path/to/paper.pdf --output /tmp/paper.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# PDF parser
# ---------------------------------------------------------------------------

def parse_pdf(filepath: str) -> dict:
    text_pages = _extract_pdf_text(filepath)
    if not text_pages:
        return {"error": f"Could not extract text from {filepath}"}
    full_text = "\n".join(text_pages)
    return _structure_academic_text(full_text, source="pdf")


def _extract_pdf_text(filepath: str) -> list:
    # Method 1: PyMuPDF
    try:
        import fitz
        doc = fitz.open(filepath)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return pages
    except ImportError:
        pass
    except Exception as exc:
        print(f"[PyMuPDF] {exc}", file=sys.stderr)

    # Method 2: pdfminer.six
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer
        pages = []
        for page_layout in extract_pages(filepath):
            text = "".join(
                el.get_text() for el in page_layout
                if isinstance(el, LTTextContainer)
            )
            pages.append(text)
        return pages
    except ImportError:
        pass
    except Exception as exc:
        print(f"[pdfminer] {exc}", file=sys.stderr)

    # Method 3: pdftotext system command
    try:
        import subprocess
        r = subprocess.run(["pdftotext", "-layout", filepath, "-"],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return r.stdout.split("\x0c")
    except Exception:
        pass

    print("[ERROR] No PDF parser found. Run: pip install pymupdf", file=sys.stderr)
    return []


# ---------------------------------------------------------------------------
# LaTeX parser
# ---------------------------------------------------------------------------

def parse_latex(dirpath: str) -> dict:
    root_file = _find_latex_root(dirpath)
    if not root_file:
        return {"error": f"No LaTeX root file found in {dirpath}"}
    full_source = _expand_latex(root_file, dirpath)
    return _extract_latex_content(full_source)


def _find_latex_root(dirpath: str) -> str:
    for name in ["main.tex", "paper.tex", "manuscript.tex", "article.tex"]:
        path = os.path.join(dirpath, name)
        if os.path.isfile(path):
            return path
    for root, _, files in os.walk(dirpath):
        for fname in sorted(files):
            if not fname.endswith(".tex"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    if "\\documentclass" in f.read(3000):
                        return fpath
            except Exception:
                pass
    return ""


def _expand_latex(tex_path: str, base_dir: str, depth: int = 0) -> str:
    if depth > 10:
        return ""
    try:
        with open(tex_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return ""

    def expand_input(m):
        fname = m.group(1).strip()
        if not fname.endswith(".tex"):
            fname += ".tex"
        for search_root in [os.path.dirname(tex_path), base_dir]:
            candidate = os.path.join(search_root, fname)
            if os.path.isfile(candidate):
                return _expand_latex(candidate, base_dir, depth + 1)
        return f"% [MISSING: {fname}]"

    content = re.sub(r"\\input\{([^}]+)\}", expand_input, content)
    content = re.sub(r"\\include\{([^}]+)\}", expand_input, content)
    return content


def _latex_to_plain(text: str) -> str:
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)
    text = text.replace(r"\%", "%")
    text = re.sub(r"\\(?:textbf|textit|emph|text|mathrm|mathbf)\{([^}]*)\}",
                  r"\1", text)
    text = re.sub(r"\\(?:cite|ref|label|eqref)\{[^}]*\}", "", text)
    text = re.sub(r"\\(?:begin|end)\{[^}]*\}", "", text)
    text = re.sub(r"\\(?:section|subsection|subsubsection)\*?\{([^}]*)\}",
                  r"\n\n## \1\n", text)
    text = re.sub(r"\\[a-zA-Z]+\*?\{([^}]{0,200})\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\s*", " ", text)
    text = re.sub(r"[{}]", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_latex_content(source: str) -> dict:
    result = {"source": "latex"}

    # Title
    m = re.search(r"\\title\{([^}]*)\}", source, re.DOTALL)
    if m:
        result["title"] = _latex_to_plain(m.group(1)).strip()

    # Abstract
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", source, re.DOTALL)
    if m:
        result["abstract"] = _latex_to_plain(m.group(1)).strip()

    # Keywords
    m = re.search(r"\\keywords?\{([^}]*)\}", source, re.DOTALL)
    if m:
        result["keywords"] = _latex_to_plain(m.group(1)).strip()

    # Sections
    section_pattern = re.compile(
        r"\\(?:section|subsection)\*?\{([^}]*)\}(.*?)"
        r"(?=\\(?:section|subsection)\*?\{|\\end\{document\})",
        re.DOTALL,
    )
    sections = {}
    for m in section_pattern.finditer(source):
        title = _latex_to_plain(m.group(1)).strip().lower()
        body = _latex_to_plain(m.group(2)).strip()[:3000]
        sections[title] = body
    result["sections"] = sections

    # Key formulas (preserve LaTeX source)
    formulas = []
    for pat in [
        r"\$\$(.+?)\$\$",
        r"\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}",
        r"\\begin\{align\*?\}(.*?)\\end\{align\*?\}",
    ]:
        for m in re.finditer(pat, source, re.DOTALL):
            f = m.group(1).strip()
            if len(f) > 5:
                formulas.append(f[:500])
    result["key_formulas"] = formulas[:20]

    # Figure captions
    captions = []
    for m in re.finditer(r"\\caption\{([^}]*)\}", source, re.DOTALL):
        cap = _latex_to_plain(m.group(1)).strip()
        if cap:
            captions.append(cap)
    result["figure_captions"] = captions[:20]

    # Contributions (itemize in intro or contribution section)
    contributions = []
    for contrib_pat in [
        r"\\(?:section|subsection)\*?\{[^}]*(?:contribution|Contribution)[^}]*\}(.*?)"
        r"(?=\\(?:section|subsection)\*?\{)",
        r"\\begin\{itemize\}(.*?)\\end\{itemize\}",
    ]:
        m = re.search(contrib_pat, source, re.DOTALL | re.IGNORECASE)
        if m:
            items = re.findall(
                r"\\item\s+(.*?)(?=\\item|\\end\{itemize\}|$)",
                m.group(1), re.DOTALL,
            )
            for item in items[:8]:
                text = _latex_to_plain(item).strip()[:400]
                if text:
                    contributions.append(text)
            if contributions:
                break
    if contributions:
        result["contributions"] = contributions

    return result


# ---------------------------------------------------------------------------
# Plain-text structure analyzer (shared for PDF output)
# ---------------------------------------------------------------------------

SECTION_KEYWORDS = {
    "abstract": ["abstract"],
    "introduction": ["introduction", "background"],
    "related_work": ["related work", "related works"],
    "method": ["method", "methodology", "approach", "proposed", "model",
               "framework", "system", "architecture"],
    "experiment": ["experiment", "evaluation", "results", "performance", "ablation"],
    "conclusion": ["conclusion", "conclusions", "summary"],
}


def _structure_academic_text(full_text: str, source: str = "pdf") -> dict:
    lines = full_text.split("\n")
    sections: dict = {}
    current_section = "preamble"
    buffer: list = []

    for line in lines:
        stripped = line.strip()
        if _is_section_header(stripped):
            if buffer:
                sections[current_section] = "\n".join(buffer).strip()
            current_section = stripped.lower()
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        sections[current_section] = "\n".join(buffer).strip()

    canonical: dict = {}
    for canon, keywords in SECTION_KEYWORDS.items():
        for sec_name, content in sections.items():
            if any(kw in sec_name for kw in keywords):
                canonical[canon] = content[:3000]
                break

    result = {
        "source": source,
        "raw_section_names": list(sections.keys()),
        **canonical,
    }

    preamble = sections.get("preamble", "")
    if preamble:
        first = preamble.strip().split("\n")[0].strip()
        if 10 < len(first) < 200:
            result["title"] = first

    formulas = re.findall(r"\$\$([^$]+)\$\$|\\\[([^\]]+)\\\]", full_text)
    result["key_formulas"] = [
        (a or b).strip() for a, b in formulas if (a or b).strip()
    ][:15]

    return result


def _is_section_header(line: str) -> bool:
    if not line or len(line) > 80 or len(line) < 3:
        return False
    if re.match(r"^\d+(\.\d+)*\s+[A-Z]", line):
        return True
    if line.isupper() and 3 < len(line) < 40:
        return True
    common = {
        "Abstract", "Introduction", "Related Work", "Method", "Methods",
        "Approach", "Model", "Framework", "Experiments", "Results",
        "Evaluation", "Ablation", "Conclusion", "Conclusions",
        "Acknowledgment", "References", "Appendix",
    }
    return line in common or any(line.startswith(kw) for kw in common)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parse academic paper (PDF or LaTeX dir)")
    parser.add_argument("path", help="PDF file or LaTeX directory path")
    parser.add_argument("--output", "-o", default="-",
                        help="Output JSON ('-' for stdout)")
    args = parser.parse_args()

    if os.path.isdir(args.path):
        print(f"[*] Parsing LaTeX directory: {args.path}", file=sys.stderr)
        result = parse_latex(args.path)
    elif os.path.isfile(args.path):
        print(f"[*] Parsing PDF: {args.path}", file=sys.stderr)
        result = parse_pdf(args.path)
    else:
        print(f"[ERROR] Not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(output)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[*] Saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
