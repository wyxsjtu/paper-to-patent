#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中国专利公布公告（http://epub.cnipa.gov.cn/）检索工具。

【重要】本工具只在**有显示器的环境**下运行（本地机器或 DISPLAY 已配置）。
  * headless=False（有界面 Chromium）可通过 Tongdun WAF，获取真实结果页
  * headless=True 被 WAF 拦截，首页永远不会出现 #searchStr，本工具拒绝以无头模式启动
  * 如在服务器上运行，请通过 SSH X11 转发（ssh -X）或 VNC 提供显示环境

环境变量
--------
  EPUB_WAF_MAX_WAIT_SEC   等待 #searchStr 出现的最长秒数（默认 180）
  EPUB_RESULT_HTML        结果页 HTML 保存路径（不设则自动命名）
  PLAYWRIGHT_BROWSERS_PATH  Playwright 浏览器路径（默认 /hdd0/playwright_browsers）

用法（命令行）
-----------
  python3 cnipa_epub_fetch.py "深度学习"          # 搜索，输出 JSON
  python3 cnipa_epub_fetch.py --dump-home          # 只拉取首页（调试用）
  python3 cnipa_epub_fetch.py "侧信道" --no-save  # 不保存 HTML，只输出 JSON

用法（作为库）
-----------
  from cnipa_epub_fetch import search_epub_keyword
  html, hits = search_epub_keyword("深度学习")
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, List, TYPE_CHECKING

# ── 依赖检查 ──────────────────────────────────────────────────────────────────

def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, TypeError):
            pass


if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright

try:
    from playwright.sync_api import Error, sync_playwright
except ImportError:
    Error = Exception  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]

try:
    from cnipa_epub_parse import EpubSearchHit, hits_to_jsonable, parse_search_result_html
except ImportError:
    # 允许作为独立脚本运行（parse 模块在同目录）
    _here = Path(__file__).resolve().parent
    sys.path.insert(0, str(_here))
    from cnipa_epub_parse import EpubSearchHit, hits_to_jsonable, parse_search_result_html

# ── 常量 ──────────────────────────────────────────────────────────────────────

EPUB_BASE = "http://epub.cnipa.gov.cn/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ── 配置读取 ──────────────────────────────────────────────────────────────────

def _max_wait_sec() -> float:
    return float(os.environ.get("EPUB_WAF_MAX_WAIT_SEC", "180"))


def _browsers_path() -> str | None:
    return os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/hdd0/playwright_browsers") or None


def _has_display() -> bool:
    """检查是否有可用的显示环境（X11 / Wayland）。"""
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("MIR_SOCKET")
    )


def default_result_html_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return Path(__file__).resolve().parent / f"_last_result_{ts}.html"


# ── 浏览器 & 上下文 ───────────────────────────────────────────────────────────

def _require_playwright() -> None:
    if sync_playwright is None:
        raise ImportError(
            "playwright 未安装。请运行：\n"
            "  pip install playwright\n"
            "  PLAYWRIGHT_BROWSERS_PATH=/hdd0/playwright_browsers "
            "python3 -m playwright install chromium"
        )


def _launch_browser(p: "Playwright") -> "Browser":
    """
    始终以 headless=False 启动（有界面模式）。
    WAF 对无头 Chromium 的指纹识别会导致首页永远不出现 #searchStr，
    因此本工具明确禁用无头模式。
    调用方应确保 DISPLAY 已设置（本地机器或 SSH X11 转发）。
    """
    bp = _browsers_path()
    kwargs: dict = dict(
        headless=False,  # 必须有界面，否则 WAF 拦截
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    if bp:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bp
    return p.chromium.launch(**kwargs)


def _new_context(browser: "Browser") -> "BrowserContext":
    return browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        locale="zh-CN",
        viewport={"width": 1280, "height": 900},
    )


# ── 等待首页可用 ──────────────────────────────────────────────────────────────

def wait_for_epub_home_ready(page: "Page", *, max_wait_sec: float | None = None) -> None:
    """
    访问首页并轮询等待 #searchStr 出现。
    Tongdun WAF 在真实浏览器下会自动解决并加载完整首页；
    轮询周期 3s，总时长由 max_wait_sec（默认 180s）控制。
    """
    limit = max_wait_sec if max_wait_sec is not None else _max_wait_sec()
    print(f"[epub] 访问首页 {EPUB_BASE}（等待 #searchStr，最长 {limit:.0f}s）...", file=sys.stderr)
    page.goto(EPUB_BASE, wait_until="load", timeout=120_000)

    elapsed = 0.0
    step = 3.0
    while elapsed < limit:
        page.wait_for_timeout(int(step * 1000))
        elapsed += step
        try:
            if page.query_selector("#searchStr"):
                print(f"[epub] #searchStr 已出现（{elapsed:.0f}s）", file=sys.stderr)
                return
        except Error:
            # 页面正在跳转，继续等待
            pass
        if elapsed % 30 < step:
            print(f"[epub] 等待中... {elapsed:.0f}/{limit:.0f}s", file=sys.stderr)

    raise TimeoutError(
        f"[epub] {limit}s 内未出现 #searchStr。\n"
        "  可能原因：\n"
        "  1. 无显示环境（DISPLAY 未设置）导致有界面 Chrome 无法启动\n"
        "  2. WAF 策略变更，需更长等待时间（增大 EPUB_WAF_MAX_WAIT_SEC）\n"
        "  3. 网络不通"
    )


# ── 提交搜索 ──────────────────────────────────────────────────────────────────

def _wait_result_page_settled(page: Page) -> None:
    try:
        page.wait_for_load_state("load", timeout=30_000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=25_000)
    except Exception:
        pass
    page.wait_for_timeout(800)


def _safe_page_content(page: Page, *, max_attempts: int = 10) -> str:
    last_err: Exception | None = None
    for i in range(max_attempts):
        try:
            return page.content()
        except Error as e:
            msg = str(e).lower()
            last_err = e
            if "navigating" not in msg and "changing" not in msg:
                raise
            try:
                page.wait_for_load_state("load", timeout=20_000)
            except Exception:
                pass
            page.wait_for_timeout(400 + 200 * i)
    if last_err:
        raise last_err
    raise RuntimeError("_safe_page_content: 未能获取页面内容")


def submit_index_search(page: Page, keyword: str) -> None:
    """将关键词写入 #searchStr 并提交 #indexForm。"""
    print(f"[epub] 提交搜索：{keyword!r}", file=sys.stderr)
    page.fill("#searchStr", keyword)
    with page.expect_navigation(timeout=120_000, wait_until="load"):
        form = page.query_selector("#indexForm")
        if form:
            form.evaluate("el => el.submit()")
        else:
            page.evaluate(
                "() => { const f = document.getElementById('indexForm'); if (f) f.submit(); }"
            )
    _wait_result_page_settled(page)
    print(f"[epub] 结果页已加载：{page.url}", file=sys.stderr)


# ── 高层 API ──────────────────────────────────────────────────────────────────

def _check_display() -> None:
    """若无显示环境，给出明确错误而不是静默失败。"""
    if not _has_display():
        raise EnvironmentError(
            "[epub] 未检测到显示环境（DISPLAY / WAYLAND_DISPLAY 均未设置）。\n"
            "\n"
            "epub.cnipa.gov.cn 的 Tongdun WAF 需要真实浏览器指纹，\n"
            "无头 Chrome 会被永久拦截，无法加载 #searchStr。\n"
            "\n"
            "解决方案（任选其一）：\n"
            "  A. 在本地有显示器的机器上运行：\n"
            "       python3 cnipa_epub_fetch.py '关键词' | ssh user@server 'cat > /tmp/r.json'\n"
            "\n"
            "  B. 通过 SSH X11 转发连接服务器：\n"
            "       ssh -X user@server\n"
            "       export DISPLAY=localhost:10.0  # 或实际 X11 DISPLAY 值\n"
            "       python3 cnipa_epub_fetch.py '关键词'\n"
            "\n"
            "  C. 在服务器上启动 Xvfb（需要安装）：\n"
            "       Xvfb :99 -screen 0 1280x900x24 &\n"
            "       export DISPLAY=:99\n"
            "       python3 cnipa_epub_fetch.py '关键词'\n"
        )


def fetch_epub_result_html(
    keyword: str,
    *,
    playwright_factory: Callable[[], "Playwright"] | None = None,
) -> str:
    """
    启动有界面 Chromium，搜索关键词，返回结果页 HTML 字符串。
    解析由 ``cnipa_epub_parse.parse_search_result_html`` 完成。
    """
    _check_display()
    _require_playwright()
    pw_gen = playwright_factory or sync_playwright
    with pw_gen() as p:
        browser = _launch_browser(p)
        context = _new_context(browser)
        try:
            page = context.new_page()
            wait_for_epub_home_ready(page)
            submit_index_search(page, keyword)
            return _safe_page_content(page)
        finally:
            context.close()
            browser.close()


def search_epub_keyword(
    keyword: str,
    *,
    playwright_factory: Callable[[], "Playwright"] | None = None,
) -> tuple[str, List[EpubSearchHit]]:
    """返回 (结果页HTML, 解析后的hit列表)。"""
    html = fetch_epub_result_html(keyword, playwright_factory=playwright_factory)
    hits = parse_search_result_html(html)
    print(f"[epub] 解析到 {len(hits)} 条结果", file=sys.stderr)
    return html, hits


def search_epub_keyword_with_page(
    page: "Page",
    keyword: str,
) -> tuple[str, List[EpubSearchHit]]:
    """复用已有 Page 对象（跨多次搜索时避免重复打开浏览器）。"""
    wait_for_epub_home_ready(page)
    submit_index_search(page, keyword)
    html = _safe_page_content(page)
    hits = parse_search_result_html(html)
    return html, hits


# ── 调试入口 ──────────────────────────────────────────────────────────────────

def _dump_home_debug() -> None:
    _check_display()
    _require_playwright()
    out = Path(__file__).resolve().parent / "_last_home.html"
    with sync_playwright() as p:
        browser = _launch_browser(p)
        context = _new_context(browser)
        page = context.new_page()
        try:
            wait_for_epub_home_ready(page)
            out.write_text(page.content(), encoding="utf-8")
            print(f"[epub] 首页已保存：{out}")
        finally:
            context.close()
            browser.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    _ensure_utf8_stdio()
    import argparse

    ap = argparse.ArgumentParser(
        description="epub.cnipa.gov.cn 专利检索（需要本地显示环境）",
        epilog=(
            "示例：\n"
            "  # 在本地机器搜索并把 JSON 通过 SSH 传回服务器\n"
            "  python3 cnipa_epub_fetch.py '深度学习' | ssh user@server 'cat > /tmp/r.json'\n"
            "\n"
            "  # SSH X11 转发后在服务器直接运行\n"
            "  ssh -X user@server\n"
            "  export DISPLAY=localhost:10.0\n"
            "  python3 cnipa_epub_fetch.py '侧信道攻击' -o /tmp/results.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("keyword", nargs="?", default="批处理", help="搜索关键词")
    ap.add_argument("-o", "--output", default="-", help="JSON 输出文件（默认 stdout）")
    ap.add_argument("--save-html", action="store_true", help="同时保存结果页 HTML")
    ap.add_argument("--no-save", action="store_true", help="不保存 HTML（仅输出 JSON）")
    ap.add_argument("--dump-home", "-d", action="store_true", help="调试：只拉取首页")
    args = ap.parse_args()

    if args.dump_home:
        _dump_home_debug()
        sys.exit(0)

    kw = args.keyword.strip()
    try:
        out_html, hits = search_epub_keyword(kw)
    except EnvironmentError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[epub] 搜索失败：{e}", file=sys.stderr)
        sys.exit(1)

    # 保存 HTML
    if args.save_html and not args.no_save:
        html_path = Path(
            os.environ.get("EPUB_RESULT_HTML", "").strip() or default_result_html_path()
        ).expanduser().resolve()
        html_path.write_text(out_html, encoding="utf-8")
        print(f"[epub] 结果页已保存：{html_path}", file=sys.stderr)

    print(f"[epub] 共 {len(hits)} 条结果", file=sys.stderr)

    out_json = json.dumps(hits_to_jsonable(hits), ensure_ascii=False, indent=2)
    if args.output == "-":
        print(out_json)
    else:
        Path(args.output).expanduser().write_text(out_json, encoding="utf-8")
        print(f"[epub] JSON 已保存：{args.output}", file=sys.stderr)
