#!/usr/bin/env python3
"""
专利交底书自查工具

对生成的 Markdown 交底书进行结构、篇幅、风格检查，输出 [PASS]/[WARN]/[FAIL] 报告。

Usage:
  python3 check_disclosure.py <disclosure.md>
  python3 check_disclosure.py <disclosure.md> --json
"""
import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 检查规则配置
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS = [
    "技术领域",
    "背景技术",
    "发明内容",
    "技术效果",
    "附图说明",
    "具体实施方式",
    "权利要求书草稿",
]

FORBIDDEN_WORDS = ["本文", "我们", "作者", "新颖的", "先进的", "新颖", "先进", "创新性"]

# 需替换词：在专利文件中应使用更合规的表达
REPLACE_WORDS = {
    "攻击成功率": "分析成功率",   # 先匹配长串，防止被短串覆盖
    "单迹攻击": "单迹分析",
    "攻击者": "分析者",
    "攻击方法": "分析方法",
    "攻击设备": "待分析设备",
    "攻击": "分析",              # 通用替换（最后匹配）
}

# 各节字数范围 (min, max, level): level = "warn" or "fail"
SECTION_WORD_LIMITS = {
    "技术领域":     (60,   200,  "warn"),
    "背景技术":     (100,  400,  "warn"),
    "发明内容":     (400,  1200, "warn"),
    "技术效果":     (60,   300,  "warn"),
    "附图说明":     (10,   200,  "warn"),
    "具体实施方式": (200,  600,  "warn"),
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _count_cjk_and_words(text: str) -> int:
    """统计中文字符数 + 英文单词数（近似字数）。"""
    cjk = len(re.findall(r"[一-鿿㐀-䶿]", text))
    words = len(re.findall(r"[a-zA-Z0-9]+", text))
    return cjk + words


def _extract_sections(text: str) -> dict:
    """
    从 Markdown 中提取各节内容，返回 {节名: 内容文本}。
    匹配 ## 标题或 # 标题。
    """
    sections = {}
    current_name = None
    current_lines = []

    for line in text.splitlines():
        m = re.match(r"^#{1,3}\s+(.+)", line)
        if m:
            if current_name is not None:
                sections[current_name] = "\n".join(current_lines).strip()
            current_name = m.group(1).strip()
            current_lines = []
        else:
            if current_name is not None:
                current_lines.append(line)

    if current_name is not None:
        sections[current_name] = "\n".join(current_lines).strip()

    return sections


# ---------------------------------------------------------------------------
# 各项检查
# ---------------------------------------------------------------------------

def check_required_sections(sections: dict) -> dict:
    missing = [s for s in REQUIRED_SECTIONS if not any(
        req in name for name in sections.keys() for req in [s]
    )]
    if missing:
        return {
            "status": "FAIL",
            "message": f"缺少必要章节: {', '.join(missing)}",
        }
    return {"status": "PASS", "message": "必要章节齐全"}


def check_forbidden_words(full_text: str) -> dict:
    found = []
    for word in FORBIDDEN_WORDS:
        if word in full_text:
            found.append(word)
    if found:
        return {
            "status": "FAIL",
            "message": f"含禁用词: {', '.join(set(found))}",
        }
    return {"status": "PASS", "message": "无禁用词"}


def check_section_lengths(sections: dict) -> list:
    results = []
    for req_name, (lo, hi, level) in SECTION_WORD_LIMITS.items():
        # Find matching section (partial match)
        matched_content = None
        for name, content in sections.items():
            if req_name in name:
                matched_content = content
                break
        if matched_content is None:
            continue
        count = _count_cjk_and_words(matched_content)
        if count < lo:
            results.append({
                "status": level.upper(),
                "message": f"「{req_name}」字数偏少({count}字，建议{lo}–{hi}字)",
            })
        elif count > hi:
            results.append({
                "status": level.upper(),
                "message": f"「{req_name}」字数偏多({count}字，建议{lo}–{hi}字)",
            })
        else:
            results.append({
                "status": "PASS",
                "message": f"「{req_name}」字数正常({count}字)",
            })
    return results


def check_quantified_effects(sections: dict) -> dict:
    for name, content in sections.items():
        if "技术效果" in name:
            has_number = bool(re.search(r"\d+[\.\d]*\s*[%％倍×x秒分钟]|[1-9]\d*\s*(条|次|个|张|帧|ms|MB|GB)", content))
            has_percent = bool(re.search(r"\d+\.?\d*\s*[%％]", content))
            has_compare = bool(re.search(r"提升|降低|减少|增加|提高|加速|超过|达到|从.*到|由.*降|由.*升", content))
            if has_number or has_percent or (has_compare and re.search(r"\d", content)):
                return {"status": "PASS", "message": "技术效果含量化指标"}
            return {"status": "WARN", "message": "技术效果未见明确量化指标（建议加入百分比/倍数/具体数值）"}
    return {"status": "WARN", "message": "未找到技术效果章节，无法检查量化指标"}


def check_figure_reference(sections: dict) -> dict:
    for name, content in sections.items():
        if "具体实施方式" in name:
            if re.search(r"如图\d*|图\s*\d+", content):
                return {"status": "PASS", "message": "具体实施方式含附图引用"}
            return {"status": "WARN", "message": '具体实施方式未引用附图（建议加入"如图1所示"等）'}
    return {"status": "WARN", "message": "未找到具体实施方式章节"}


def check_step_numbering(sections: dict) -> dict:
    for name, content in sections.items():
        if "具体实施方式" in name:
            if re.search(r"[①②③④⑤⑥⑦⑧]", content):
                return {"status": "PASS", "message": "具体实施方式含步骤编号①②③…"}
            return {"status": "WARN", "message": "具体实施方式未见步骤编号①②③（建议使用圆圈数字标注步骤）"}
    return {"status": "WARN", "message": "未找到具体实施方式章节"}


def check_para_numbering(full_text: str) -> dict:
    """检查是否有 [0001] 段落编号风格。"""
    if re.search(r"\[0\d{3}\]", full_text):
        return {"status": "PASS", "message": "含 [0001] 段落编号"}
    return {"status": "WARN", "message": "未见 [0001] 段落编号（参考 PDF 风格：每段前加编号）"}


def check_solution_phrase(sections: dict) -> dict:
    """检查发明内容是否含"本发明是通过以下技术方案实现的"。"""
    for name, content in sections.items():
        if "发明内容" in name:
            if "通过以下技术方案实现" in content:
                return {"status": "PASS", "message": "发明内容含标准过渡句"}
            return {"status": "WARN", "message": '发明内容缺少"本发明是通过以下技术方案实现的"标准句'}
    return {"status": "WARN", "message": "未找到发明内容章节"}


def check_invention_title(full_text: str) -> dict:
    """检查发明名称是否存在且无评价性用语。"""
    m = re.search(r"^#\s+(.+)", full_text, re.MULTILINE)
    if not m:
        return {"status": "FAIL", "message": "未找到发明名称（文档首行应为 # 发明名称）"}
    title = m.group(1)
    bad_words = ["新型", "先进", "创新", "高效", "智能化", "最优"]
    for w in bad_words:
        if w in title:
            return {"status": "WARN", "message": f'发明名称含评价性用语"{w}"，建议删除'}
    if len(title) > 35:
        return {"status": "WARN", "message": f"发明名称偏长({len(title)}字)，建议控制在25–32字以内"}
    return {"status": "PASS", "message": f"发明名称合规: {title[:50]}"}


def check_replace_words(full_text: str) -> list:
    """检查是否含应替换为更合规表达的词汇。"""
    results = []
    found_keys = set()
    for word, replacement in REPLACE_WORDS.items():
        if word in full_text and word not in found_keys:
            found_keys.add(word)
            results.append({
                "status": "WARN",
                "message": f'含词"{word}"，专利文件中建议替换为"{replacement}"',
            })
    if not results:
        results.append({"status": "PASS", "message": "无需替换词"})
    return results


def check_figure_count(full_text: str, sections: dict) -> dict:
    """检查附图说明中的图数量与正文 Mermaid 代码块数量是否一致。"""
    # 统计正文中的 mermaid 块（含图片引用替换后的 PNG 行）
    mermaid_blocks = len(re.findall(r"```mermaid", full_text))
    # 统计 PNG 图片引用（mermaid 已转换后的形式）
    png_refs = len(re.findall(r"!\[.*?\]\(fig_\d+_.*?\.png\)", full_text))
    count_mermaid = max(mermaid_blocks, png_refs)

    # 统计附图说明节中"图N为"条目数
    count_fig_desc = 0
    for name, content in sections.items():
        if "附图说明" in name:
            count_fig_desc = len(re.findall(r"图\s*\d+\s*为", content))
            break

    if count_fig_desc == 0 and count_mermaid == 0:
        return {"status": "WARN", "message": "附图说明为空且无 Mermaid 块，建议至少提供一张流程图"}
    if count_mermaid != count_fig_desc:
        return {
            "status": "FAIL",
            "message": (
                f"附图说明声明 {count_fig_desc} 张图，"
                f"但正文含 {count_mermaid} 个 Mermaid/PNG 块，数量不一致"
            ),
        }
    return {"status": "PASS", "message": f"附图说明与 Mermaid 块数量一致（{count_mermaid} 张）"}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_checks(md_path: str) -> list:
    text = Path(md_path).read_text(encoding="utf-8")
    sections = _extract_sections(text)

    results = []

    results.append(("发明名称", check_invention_title(text)))
    results.append(("必要章节", check_required_sections(sections)))
    results.append(("禁用词", check_forbidden_words(text)))
    results.append(("标准过渡句", check_solution_phrase(sections)))
    results.append(("段落编号", check_para_numbering(text)))

    for r in check_section_lengths(sections):
        results.append(("章节字数", r))

    results.append(("量化效果", check_quantified_effects(sections)))
    results.append(("附图引用", check_figure_reference(sections)))
    results.append(("步骤编号", check_step_numbering(sections)))
    results.append(("附图数量一致", check_figure_count(text, sections)))
    for r in check_replace_words(text):
        results.append(("需替换词", r))

    return results


def _status_icon(status: str) -> str:
    return {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}.get(status, "[????]")


def main():
    parser = argparse.ArgumentParser(description="专利交底书自查工具")
    parser.add_argument("disclosure_md", help="待检查的 Markdown 交底书路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    if not Path(args.disclosure_md).is_file():
        print(f"[ERROR] 文件不存在: {args.disclosure_md}", file=sys.stderr)
        sys.exit(1)

    results = run_checks(args.disclosure_md)

    if args.json:
        out = [{"check": name, "status": r["status"], "message": r["message"]}
               for name, r in results]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    fail_count = warn_count = pass_count = 0
    for check_name, r in results:
        icon = _status_icon(r["status"])
        print(f"{icon} [{check_name}] {r['message']}")
        if r["status"] == "FAIL":
            fail_count += 1
        elif r["status"] == "WARN":
            warn_count += 1
        else:
            pass_count += 1

    print()
    print(f"总计: {pass_count} PASS / {warn_count} WARN / {fail_count} FAIL")
    if fail_count > 0:
        print("请修正所有 [FAIL] 项后重新生成。")
        sys.exit(1)
    elif warn_count > 0:
        print("存在 [WARN] 项，建议评估后酌情调整。")
    else:
        print("自查通过。")


if __name__ == "__main__":
    main()
