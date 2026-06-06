#!/usr/bin/env bash
# Convert all Mermaid code blocks in a Markdown file to PNG images.
#
# Usage:
#   bash mermaid_to_png.sh <input.md> <output_dir>
#
# Strategy (in order):
#   1. mmdc (mermaid-cli, @mermaid-js/mermaid-cli)
#   2. mermaid.ink API (online, no local install needed)
#   3. Print instructions and skip
#
# Output files: fig_01_<label>.png, fig_02_<label>.png, ...
# The script also prints the updated Markdown with mermaid blocks replaced by
# ![...](png_path) references to stdout.

set -euo pipefail

export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

INPUT_MD="${1:-}"
OUTPUT_DIR="${2:-.}"

if [[ -z "$INPUT_MD" || ! -f "$INPUT_MD" ]]; then
    echo "Usage: $0 <input.md> [output_dir]" >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# ---- helpers ---------------------------------------------------------------

log() { echo "[mermaid_to_png] $*" >&2; }

# base64-encode a file, URL-safe (no padding issues)
base64_url_encode() {
    base64 -w 0 "$1" | tr '+/' '-_'
}

# Download from mermaid.ink API
fetch_mermaid_ink() {
    local code="$1"
    local outfile="$2"
    local tmpcode
    tmpcode=$(mktemp /tmp/mermaid_XXXXXX.mmd)
    echo "$code" > "$tmpcode"

    local encoded
    encoded=$(base64 -w 0 "$tmpcode" | tr '+/' '-_')
    rm -f "$tmpcode"

    local url="https://mermaid.ink/img/${encoded}?type=png"
    log "Fetching from mermaid.ink: ${url:0:80}..."

    if command -v curl &>/dev/null; then
        curl -fsSL -o "$outfile" "$url" && return 0
    elif command -v wget &>/dev/null; then
        wget -q -O "$outfile" "$url" && return 0
    fi
    return 1
}

# ---- extract and convert mermaid blocks ------------------------------------

UPDATED_MD="$OUTPUT_DIR/_updated.md"
cp "$INPUT_MD" "$UPDATED_MD"

fig_index=0
in_block=0
block_lines=()
block_label=""

# We need a two-pass approach: first extract all blocks, then replace in file.
# Use Python for reliable extraction if available; otherwise use awk.

extract_blocks_py() {
    python3 - "$INPUT_MD" <<'PYEOF'
import sys, re, json

md_path = sys.argv[1]
with open(md_path, 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'```mermaid\s*\n(.*?)\n```', re.DOTALL)
blocks = []
for i, m in enumerate(pattern.finditer(content)):
    before = content[:m.start()]
    after = content[m.end():]
    label = ""
    all_matches = re.findall(r'图\s*(\d+)\s*为([^；;\n]+)', content)
    for num, desc in all_matches:
        if int(num) == i + 1:
            label = desc.strip()
            break
    if not label:
        next_match = re.search(r'图\s*(\d+)\s*为([^；;\n]+)', after)
        if next_match and int(next_match.group(1)) == i + 1:
            label = next_match.group(2).strip()
    blocks.append({
        "index": i + 1,
        "code": m.group(1),
        "label": label,
        "start": m.start(),
        "end": m.end(),
        "full_match": m.group(0),
    })
print(json.dumps(blocks, ensure_ascii=False))
PYEOF
}

if command -v python3 &>/dev/null; then
    BLOCKS_JSON=$(extract_blocks_py)
    BLOCK_COUNT=$(python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" <<< "$BLOCKS_JSON")
else
    log "python3 not found; cannot parse Mermaid blocks"
    BLOCK_COUNT=0
    BLOCKS_JSON="[]"
fi

if [[ "$BLOCK_COUNT" -eq 0 ]]; then
    log "No Mermaid blocks found in $INPUT_MD"
    cat "$INPUT_MD"
    exit 0
fi

log "Found $BLOCK_COUNT Mermaid block(s)"

# ---- convert each block ----------------------------------------------------

REPLACEMENTS_JSON="[]"

python3 - "$INPUT_MD" "$OUTPUT_DIR" "$BLOCKS_JSON" <<'PYEOF'
import sys, re, json, subprocess, os, base64, urllib.request, shutil

md_path    = sys.argv[1]
output_dir = sys.argv[2]
blocks     = json.loads(sys.argv[3])

with open(md_path, 'r', encoding='utf-8') as f:
    content = f.read()

def slug_from_code(code, index):
    """Generate a short filename label from mermaid code."""
    first_word = ""
    for line in code.split('\n'):
        line = line.strip()
        if line and not line.startswith('%') and not line.startswith('graph') \
                and not line.startswith('flowchart') and not line.startswith('sequenceDiagram'):
            words = re.findall(r'[一-鿿\w]+', line)
            if words:
                first_word = words[0][:8]
                break
    return first_word or f"diagram{index}"

def sanitize_label(label, index):
    words = re.findall(r'[一-鿿A-Za-z0-9_]+', label or '')
    slug = ''.join(words)[:24]
    return slug or None

def try_mmdc(code, outfile):
    if shutil.which('mmdc') is None:
        return False
    tmpf = f"/tmp/mermaid_{os.getpid()}.mmd"
    with open(tmpf, 'w', encoding='utf-8') as f:
        f.write(code)
    try:
        r = subprocess.run(
            ['mmdc', '-i', tmpf, '-o', outfile, '-b', 'white', '--width', '1200'],
            capture_output=True, timeout=30,
        )
        os.unlink(tmpf)
        return r.returncode == 0 and os.path.isfile(outfile)
    except Exception as e:
        print(f"  [mmdc] failed: {e}", file=sys.stderr)
        if os.path.exists(tmpf):
            os.unlink(tmpf)
        return False

def try_mermaid_ink(code, outfile):
    try:
        encoded = base64.b64encode(code.encode('utf-8')).decode('ascii')
        # URL-safe base64
        encoded = encoded.replace('+', '-').replace('/', '_')
        url = f"https://mermaid.ink/img/{encoded}?type=png"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        if data[:4] == b'\x89PNG':
            with open(outfile, 'wb') as f:
                f.write(data)
            return True
    except Exception as e:
        print(f"  [mermaid.ink] failed: {e}", file=sys.stderr)
    return False

replacements = []
for block in blocks:
    idx   = block['index']
    code  = block['code']
    label = sanitize_label(block.get('label', ''), idx) or slug_from_code(code, idx)
    fname = f"fig_{idx:02d}_{label}.png"
    fpath = os.path.join(output_dir, fname)

    print(f"  Block {idx}: {label} -> {fname}", file=sys.stderr)

    success = False
    if not success:
        print(f"    Trying mmdc...", file=sys.stderr)
        success = try_mmdc(code, fpath)
    if not success:
        print(f"    Trying mermaid.ink API...", file=sys.stderr)
        success = try_mermaid_ink(code, fpath)

    if success:
        print(f"    OK: {fpath}", file=sys.stderr)
        replacements.append({
            "full_match": block['full_match'],
            "replacement": f"![图{idx} {label}]({fname})",
        })
    else:
        print(f"    FAILED: keeping Mermaid source (install mmdc or check network)",
              file=sys.stderr)
        replacements.append({
            "full_match": block['full_match'],
            "replacement": block['full_match'],  # keep original
        })

# Apply replacements
updated = content
for r in replacements:
    updated = updated.replace(r['full_match'], r['replacement'], 1)

updated_path = os.path.join(output_dir, '_updated.md')
with open(updated_path, 'w', encoding='utf-8') as f:
    f.write(updated)

print(updated)
PYEOF

log "Done. Updated Markdown written to $OUTPUT_DIR/_updated.md"
