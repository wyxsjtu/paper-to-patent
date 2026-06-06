#!/usr/bin/env bash
# Setup script for patent-disclosure skill.
# Installs Python packages, Node.js tools, and system utilities.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

echo "================================================"
echo " Patent Disclosure Skill — Dependency Setup"
echo "================================================"

# ---- Python packages -------------------------------------------------------
echo ""
echo "[1/4] Installing Python packages..."
PIP_PKGS="requests beautifulsoup4 lxml pymupdf python-docx playwright"
OPTIONAL_PKGS="pdfminer.six"

if command -v pip3 &>/dev/null; then
    pip3 install --quiet $PIP_PKGS
    pip3 install --quiet $OPTIONAL_PKGS 2>/dev/null || \
        echo "  (pdfminer.six optional, skipped)"
    echo "  Python packages: OK"
elif command -v pip &>/dev/null; then
    pip install --quiet $PIP_PKGS
    echo "  Python packages: OK"
else
    echo "  [WARN] pip not found. Install Python packages manually:"
    echo "    pip install $PIP_PKGS"
fi

# ---- pandoc ----------------------------------------------------------------
echo ""
echo "[2/4] Checking pandoc..."
if command -v pandoc &>/dev/null; then
    echo "  pandoc: $(pandoc --version | head -1) — OK"
else
    echo "  pandoc not found. Installing..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y pandoc 2>/dev/null || \
            echo "  [WARN] Could not install pandoc via apt. Try: sudo apt install pandoc"
    elif command -v brew &>/dev/null; then
        brew install pandoc 2>/dev/null || \
            echo "  [WARN] Could not install pandoc via brew."
    else
        echo "  [WARN] Please install pandoc manually: https://pandoc.org/installing.html"
    fi
fi

# ---- Node.js + mermaid-cli (mmdc) ------------------------------------------
echo ""
echo "[3/4] Checking mermaid-cli (mmdc)..."
if command -v mmdc &>/dev/null; then
    echo "  mmdc: $(mmdc --version 2>/dev/null || echo 'found') — OK"
else
    if command -v npm &>/dev/null; then
        echo "  npm found, installing @mermaid-js/mermaid-cli..."
        npm install -g @mermaid-js/mermaid-cli --quiet 2>/dev/null && \
            echo "  mmdc: installed OK" || \
            echo "  [WARN] mmdc install failed. Fallback: mermaid.ink API will be used."
    elif command -v npx &>/dev/null; then
        echo "  npx found (mmdc available via npx @mermaid-js/mermaid-cli)"
    else
        echo "  [WARN] npm/npx not found. Mermaid diagrams will use mermaid.ink API."
        echo "         Ensure internet access for diagram generation."
    fi
fi

# ---- pdftotext (poppler-utils) ---------------------------------------------
echo ""
echo "[4/4] Checking PDF tools..."
if command -v pdftotext &>/dev/null; then
    echo "  pdftotext: OK"
else
    echo "  pdftotext not found (optional)."
    if command -v apt-get &>/dev/null; then
        sudo apt-get install -y poppler-utils 2>/dev/null || true
    fi
fi

# ---- Playwright Chromium ---------------------------------------------------
echo ""
echo "[3.5/4] Installing Playwright Chromium (备用 epub.cnipa.gov.cn 检索源需要)..."
BROWSERS_PATH="${BROWSERS_PATH:-/hdd0/playwright_browsers}"
if [[ ! -d "$BROWSERS_PATH" ]]; then
    mkdir -p "$BROWSERS_PATH"
fi
if PLAYWRIGHT_BROWSERS_PATH="$BROWSERS_PATH" python3 -m playwright install chromium --quiet 2>/dev/null; then
    echo "  Playwright Chromium: OK (安装目录: $BROWSERS_PATH)"
else
    echo "  [WARN] Playwright Chromium 安装失败，将无法使用备用 epub.cnipa.gov.cn 检索源。"
    echo "         手动安装: PLAYWRIGHT_BROWSERS_PATH=$BROWSERS_PATH python3 -m playwright install chromium"
fi

# ---- Create pandoc reference template -------------------------------------
echo ""
echo "[*] Generating pandoc reference.docx template..."
TEMPLATE_DIR="$SKILL_DIR/templates"
REF_DOCX="$TEMPLATE_DIR/reference.docx"

if [[ ! -f "$REF_DOCX" ]]; then
    python3 - "$REF_DOCX" <<'PYEOF' && \
        echo "  reference.docx: created at $REF_DOCX" || \
        echo "  [WARN] Could not create reference.docx (install python-docx)"
import sys
from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn

out = sys.argv[1]
doc = Document()

def set_font(style, east_asia, western, size, bold=None):
    style.font.name = western
    style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    style._element.rPr.rFonts.set(qn("w:eastAsia"), east_asia)
    style._element.rPr.rFonts.set(qn("w:ascii"), western)
    style._element.rPr.rFonts.set(qn("w:hAnsi"), western)

normal = doc.styles["Normal"]
set_font(normal, "宋体", "Times New Roman", 12)
normal.paragraph_format.first_line_indent = Pt(24)
normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
normal.paragraph_format.space_after = Pt(0)

for i in range(1, 5):
    h = doc.styles[f"Heading {i}"]
    set_font(h, "黑体", "Times New Roman", 14 if i == 1 else 12, True)
    h.paragraph_format.first_line_indent = Pt(0)
    h.paragraph_format.space_before = Pt(6)
    h.paragraph_format.space_after = Pt(6)

for name in ("List Bullet", "List Number", "Caption"):
    try:
        style = doc.styles[name]
        set_font(style, "宋体", "Times New Roman", 12 if name != "Caption" else 10.5)
        style.paragraph_format.first_line_indent = Pt(0)
    except Exception:
        pass

doc.add_heading("发明专利技术交底书", level=1)
doc.add_paragraph("正文段落。")
doc.save(out)
PYEOF
elif [[ -f "$REF_DOCX" ]]; then
    echo "  reference.docx: already exists"
fi

# ---- Summary ---------------------------------------------------------------
echo ""
echo "================================================"
echo " Setup complete. Summary:"
echo "  Python parser: pymupdf/pdfminer"
echo "  Word output:   pandoc (primary) + python-docx (fallback)"
echo "  Diagrams:      mmdc (if installed) -> mermaid.ink API"
echo ""
echo " To run the skill, use:"
echo "  /patent-disclosure /path/to/paper.pdf"
echo "================================================"
