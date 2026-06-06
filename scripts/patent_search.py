#!/usr/bin/env python3
"""
中国专利检索工具（多源）

Sources（优先级顺序）：
  1. gov    — 国家政务服务平台 / CNIPA 公布公告查询（无需显示器）
  2. epub   — epub.cnipa.gov.cn 公布公告（需本地有显示器；Playwright non-headless）
  3. google — Google Patents JSON API（服务器可能无法访问）

Usage:
  python3 patent_search.py --query "深度学习 图像分割" [--max 8]
                           [--output results.json] [--source all|cnipa|gov|epub|google]

说明：
  * gov 源来自国家政务服务平台的"国家知识产权局-中国专利公布公告查询"，
    无需浏览器，适合服务器环境。
  * epub 源需要 DISPLAY 环境变量（本地机器或 SSH X11 转发后运行）。
    在无显示器的服务器上直接运行时会给出明确错误提示，不会挂起。
  * 所有源均无结果时，返回 no_results 并引导使用 WebSearch 工具。
"""
import argparse
import hashlib
import itertools
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

try:
    import requests
except ImportError:
    print("[ERROR] pip install requests", file=sys.stderr)
    sys.exit(1)

TIMEOUT = 20
CNIPA_GOV_ENDPOINT = "https://app.gjzwfw.gov.cn/jimps/link.do"
CNIPA_GOV_REFERER = "https://app.gjzwfw.gov.cn/jmopen/webapp/html5/zlgbggcx/index.html"
CNIPA_GOV_PATENT_KEY = "6f0c5ce612ba4471acce875dd7e6f6a2"

HDR_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# 源 1：国家政务服务平台 / CNIPA 公布公告查询（无显示环境可用）
# ---------------------------------------------------------------------------

def search_cnipa_gov(query: str, max_results: int = 10) -> list:
    """
    调用国家政务服务平台的"国家知识产权局-中国专利公布公告查询"接口。

    该入口页面标注"本服务由国家知识产权局提供"。相比 epub 源，此接口
    不需要 DISPLAY 或浏览器，适合作为服务器默认检索源。
    """
    request_time = int(time.time() * 1000)
    condition = {
        "from": "1",
        "key": CNIPA_GOV_PATENT_KEY,
        "sign": hashlib.md5(f"zscqgbgg{request_time}".encode()).hexdigest(),
        "requestTime": request_time,
        "raw": {
            "searchStr": query,
            "from": 0,
            "size": max_results,
            "pubtypeList": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        },
    }

    try:
        resp = requests.post(
            CNIPA_GOV_ENDPOINT,
            data={"param": json.dumps(condition, ensure_ascii=False)},
            headers={
                **HDR_BROWSER,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://app.gjzwfw.gov.cn",
                "Referer": CNIPA_GOV_REFERER,
            },
            timeout=(6, TIMEOUT),
        )
        resp.raise_for_status()
        data = json.loads(resp.text)
    except Exception as exc:
        print(f"[CNIPA Gov] {exc}", file=sys.stderr)
        return []

    pat_type_map = {
        1: "发明公布",
        2: "发明公布更正",
        3: "发明授权",
        4: "发明授权更正",
        5: "发明解密",
        6: "实用新型",
        7: "实用新型更正",
        8: "实用新型解密",
        9: "外观设计",
        10: "外观设计更正",
    }

    results = []
    for p in data.get("patentList", [])[:max_results]:
        pub_no = p.get("pn") or p.get("zxgbh") or ""
        app_no = p.get("an") or ""
        url = p.get("codeUrl") or ""
        if not url and pub_no:
            url = f"http://epub.cnipa.gov.cn/patent/{pub_no}"
        results.append({
            "source": "cnipa_gov",
            "patent_no": pub_no or app_no,
            "application_no": app_no,
            "title": p.get("ti", ""),
            "applicant": p.get("e71_73", ""),
            "date": _fmt_cnipa_date(p.get("pd") or p.get("ggr") or p.get("ad")),
            "application_date": _fmt_cnipa_date(p.get("ad")),
            "abstract": p.get("abs", ""),
            "ipc": p.get("e51", ""),
            "pat_type": pat_type_map.get(p.get("pubtype"), str(p.get("pubtype", ""))),
            "url": url,
        })
    return results


def _fmt_cnipa_date(value) -> str:
    s = str(value or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


# ---------------------------------------------------------------------------
# 源 2：epub.cnipa.gov.cn（公布公告检索）
# ---------------------------------------------------------------------------

def search_epub(query: str, max_results: int = 10) -> list:
    """
    调用 cnipa_epub_fetch.search_epub_keyword 搜索公布公告网站。
    需要 DISPLAY 环境变量（有界面 Chromium）；无显示器时返回空列表并打印说明。
    """
    if not _has_display_env():
        print(
            "[epub] ⚠️  无显示环境，跳过 epub.cnipa.gov.cn 检索。\n"
            "  在本地机器（有显示器）上运行以获取结果：\n"
            "    python3 patent_search.py --query '...' --source epub\n"
            "  或通过 SSH X11 转发（ssh -X）连接后运行。",
            file=sys.stderr,
        )
        return []

    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here))

    try:
        from cnipa_epub_fetch import search_epub_keyword
    except ImportError as e:
        print(f"[epub] 导入失败: {e}", file=sys.stderr)
        return []
    except SystemExit as e:
        print(f"[epub] 依赖初始化失败，跳过 epub 源: {e}", file=sys.stderr)
        return []

    try:
        _, hits = search_epub_keyword(query)
    except Exception as exc:
        print(f"[epub] 搜索失败: {exc}", file=sys.stderr)
        return []

    out = []
    for h in hits[:max_results]:
        out.append({
            "source":    "cnipa_epub",
            "patent_no": h.pub_no,
            "title":     h.title,
            "applicant": h.applicant,
            "date":      h.pub_date,
            "abstract":  "",
            "ipc":       h.ipc,
            "pat_type":  h.pat_type,
            "url":       h.url,
        })
    return out


def _has_display_env() -> bool:
    """检查是否有可用的显示环境（X11 / Wayland）。"""
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("MIR_SOCKET")
    )


# ---------------------------------------------------------------------------
# 源 3：Google Patents JSON API
# ---------------------------------------------------------------------------

def search_google_patents(query: str, max_results: int = 10) -> list:
    url = (
        "https://patents.google.com/xhr/query?url=q%3D"
        + quote(query)
        + "%26hl%3Dzh%26country%3DCN&exp=&download=false"
    )
    try:
        resp = requests.get(
            url,
            headers={**HDR_BROWSER, "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[Google Patents] {exc}", file=sys.stderr)
        return []

    results = []
    for cluster in data.get("results", {}).get("cluster", [])[:max_results]:
        for pat in cluster.get("result", []):
            p = pat.get("patent", {})
            no = p.get("publication_number", "")
            assignee = p.get("assignee", [])
            results.append({
                "source":    "google_patents",
                "patent_no": no,
                "title":     p.get("title", ""),
                "applicant": (
                    ", ".join(assignee) if isinstance(assignee, list) else assignee
                ),
                "date":      p.get("filing_date", ""),
                "abstract":  p.get("abstract", "")[:300],
                "ipc":       ", ".join(p.get("ipc", [])),
                "url":       f"https://patents.google.com/patent/{no}",
            })
    return results


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 子查询拆分：两两组合优先，长词（>=5字）额外单独查
# ---------------------------------------------------------------------------

def _build_subqueries(query: str, long_word_threshold: int = 5, max_sub: int = 6) -> list:
    """
    将多词查询拆分为子查询列表，按以下优先级构造：
      1. 所有两两组合（相邻对优先），最多取 max_sub 个；
      2. 字符数 >= long_word_threshold 的单词单独作为子查询。
    词数 <= 2 时直接返回原查询。
    """
    words = query.split()
    if len(words) <= 2:
        return [query]

    seen: set = set()
    subs: list = []

    # 1. 相邻两两组合（语义最相关，优先尝试）
    for i in range(len(words) - 1):
        sq = f"{words[i]} {words[i + 1]}"
        if sq not in seen:
            seen.add(sq)
            subs.append(sq)

    # 2. 非相邻两两组合
    for i, j in itertools.combinations(range(len(words)), 2):
        if j == i + 1:
            continue  # 已在步骤 1 添加
        sq = f"{words[i]} {words[j]}"
        if sq not in seen:
            seen.add(sq)
            subs.append(sq)

    # 3. 字符数较多的单词单独查（长词往往是领域特定术语，单独查命中率高）
    for w in words:
        if len(w) >= long_word_threshold and w not in seen:
            seen.add(w)
            subs.append(w)

    return subs[:max_sub]


def _search_with_split(query: str, max_results: int, source: str) -> list:
    """
    先尝试原始查询；若无结果，按两两组合+长词单查策略依次检索并合并去重。
    """
    found = _do_search(query, max_results, source)
    if found:
        return found

    # 原始查询无结果 -> 子查询重试
    subqueries = _build_subqueries(query)
    if len(subqueries) == 1 and subqueries[0] == query:
        # 词数本就 <= 2，不必再拆
        return found

    print(f"    [!] 原始查询无结果，尝试子查询: {subqueries}", file=sys.stderr)
    seen_keys: set = set()
    merged: list = []
    for sq in subqueries:
        r = _do_search(sq, max_results, source)
        for item in r:
            key = item.get("patent_no") or item.get("title", "")
            if key and key not in seen_keys:
                seen_keys.add(key)
                merged.append(item)
        if len(merged) >= max_results:
            break
        time.sleep(0.8)
    return merged


def _do_search(query: str, max_results: int, source: str) -> list:
    """对单条查询按 source 调用各检索源，返回合并去重后的结果列表。"""
    found: list = []

    if source in ("gov", "cnipa", "all"):
        r = search_cnipa_gov(query, max_results)
        print(f"    CNIPA Gov [{query!r}]: {len(r)}", file=sys.stderr)
        found.extend(r)

    if source in ("epub", "all") and len(found) < max_results:
        r = search_epub(query, max_results)
        print(f"    epub [{query!r}]: {len(r)}", file=sys.stderr)
        found.extend(r)

    if source in ("google", "all") and len(found) < max_results:
        r = search_google_patents(query, max_results - len(found))
        print(f"    Google [{query!r}]: {len(r)}", file=sys.stderr)
        found.extend(r)

    return found


def main():
    ap = argparse.ArgumentParser(
        description="中国专利检索（CNIPA 政务平台 + epub.cnipa.gov.cn + Google Patents）",
        epilog=(
            "提示：\n"
            "  gov/cnipa 源无需显示器，适合服务器环境。\n"
            "  epub 源需要本地显示器。在服务器上请先 ssh -X 后再运行，\n"
            "  或在本地运行并将结果 JSON 传回服务器：\n"
            "    python3 patent_search.py -q '...' | ssh user@server 'cat > /tmp/r.json'\n"
            "\n"
            "  长查询（>2词）自动拆分为两两组合子查询重试；长词单独查；所有源均失败时建议使用 WebSearch。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--query", "-q", action="append", required=True,
                    help="搜索关键词（可多次指定）")
    ap.add_argument("--max", "-m", type=int, default=8,
                    help="每个查询最多返回条数（默认 8）")
    ap.add_argument("--output", "-o", default="-",
                    help="输出 JSON 文件（默认 stdout）")
    ap.add_argument(
        "--source",
        choices=["gov", "cnipa", "epub", "google", "all"],
        default="all",
        help="搜索源（默认 all：gov 优先，再 epub/google）",
    )
    args = ap.parse_args()

    all_results: list = []

    for query in args.query:
        print(f"[*] 搜索: {query!r}", file=sys.stderr)
        found = _search_with_split(query, args.max, args.source)
        all_results.extend(found)
        time.sleep(1.2)

    # 去重
    seen, deduped = set(), []
    for r in all_results:
        key = r.get("patent_no") or r.get("title", "")
        if key and key not in seen:
            seen.add(key)
            deduped.append(r)

    if not deduped:
        print("[!] 未找到结果。", file=sys.stderr)
        print(
            "[!] 建议：使用 Claude WebSearch 工具搜索，格式：",
            file=sys.stderr,
        )
        for q in args.query:
            print(f'[!]   "{q} 发明专利 CN"', file=sys.stderr)
        deduped.append({
            "source": "no_results",
            "queries": args.query,
            "suggestion": (
                "请使用 Claude WebSearch 工具或手动访问 "
                "http://epub.cnipa.gov.cn/ 搜索"
            ),
        })

    out = json.dumps(deduped, ensure_ascii=False, indent=2)
    if args.output == "-":
        print(out)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"[*] 已保存到 {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
