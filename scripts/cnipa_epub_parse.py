#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
epub.cnipa.gov.cn 搜索结果页 HTML 解析器。

与 cnipa_epub_fetch.py 配合使用：
  from cnipa_epub_parse import EpubSearchHit, hits_to_jsonable, parse_search_result_html

解析逻辑（多策略降级）：
  1. 精确 CSS 选择器匹配结果列表 (.search-result / .patent-list / table 等)
  2. 提取含专利号（CN\d+[A-Z]?）的行/块，附带附近文本
  3. 正则从纯文本中提取专利号+标题

EpubSearchHit 字段：
  pub_no      公开/公告号，如 CN114xxxxA
  title       发明名称
  applicant   申请人/专利权人
  pub_date    公开日（YYYY-MM-DD 或原始字符串）
  ipc         IPC 分类号（主分类）
  url         专利详情链接
  pat_type    专利类型（发明/实用新型/外观）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    raise ImportError("请安装 beautifulsoup4：pip install beautifulsoup4")

EPUB_BASE = "http://epub.cnipa.gov.cn"

# ── 专利号正则 ───────────────────────────────────────────────────────────────
_PAT_NO_RE = re.compile(r'\b(CN\s*\d{6,13}[A-Za-z]?)\b', re.IGNORECASE)
_DATE_RE   = re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{8})')
_IPC_RE    = re.compile(r'\b([A-H]\d{2}[A-Z]\s*\d+/\d+)\b')


@dataclass
class EpubSearchHit:
    pub_no:    str = ""
    title:     str = ""
    applicant: str = ""
    pub_date:  str = ""
    ipc:       str = ""
    url:       str = ""
    pat_type:  str = ""

    def __bool__(self):
        return bool(self.pub_no or self.title)


def hits_to_jsonable(hits: List[EpubSearchHit]) -> list:
    return [asdict(h) for h in hits if h]


# ── 公共辅助 ─────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text or "").strip()


def _norm_pat_no(raw: str) -> str:
    return re.sub(r'\s+', '', raw).upper()


def _extract_detail_url(tag: Tag, pub_no: str) -> str:
    """从 <a> 标签或 JS onclick 提取详情链接；失败则构造。"""
    link = tag.find('a', href=True) if isinstance(tag, Tag) else None
    if link:
        href = link['href'].strip()
        if href.startswith('http'):
            return href
        return EPUB_BASE + href if href.startswith('/') else href
    # onclick 中的 JS 跳转
    onclick = tag.get('onclick', '') if isinstance(tag, Tag) else ''
    m = re.search(r'["\']([^"\']*patentId[^"\']*)["\']', onclick, re.I)
    if m:
        return EPUB_BASE + '/' + m.group(1).lstrip('/')
    # 兜底：按专利号构造
    if pub_no:
        return f"{EPUB_BASE}/patent/{pub_no}"
    return ""


# ── 策略 1：精确结构解析 ─────────────────────────────────────────────────────

_RESULT_CONTAINERS = [
    # epub.cnipa.gov.cn 常见结构
    '.search-result', '.result-list', '.patent-list',
    '#searchResult', '#result', '.list-wrapper',
    'table.resultTable', 'table.list-table', 'table.table',
    # 通用容器
    '.content-list', '.data-list', 'ul.list', 'ol.list',
]

_LIST_ITEM_SELECTORS = [
    'li', 'tr:not(:first-child)', 'tr:not(thead tr)',
    '.item', '.patent-item', '.result-item',
]

_FIELD_LABELS = {
    'pub_no':    ['公开号', '公告号', '公布号', '申请号', '专利号', '号'],
    'title':     ['名称', '发明名称', '标题', '题目'],
    'applicant': ['申请人', '专利权人', '权利人'],
    'pub_date':  ['公开日', '公告日', '公布日', '申请日', '日期'],
    'ipc':       ['IPC', 'IPC分类号', '分类号'],
    'pat_type':  ['类型', '专利类型'],
}


def _field_from_label(text: str) -> str:
    """根据标签文字猜测字段名。"""
    for fname, labels in _FIELD_LABELS.items():
        if any(lbl in text for lbl in labels):
            return fname
    return ""


def _parse_structured_row(row: Tag) -> EpubSearchHit | None:
    """解析表格行或列表项，返回 hit；不含专利号则返回 None。"""
    hit = EpubSearchHit()
    cells = row.find_all(['td', 'dd', 'span', 'div'], recursive=False) or row.find_all(['td', 'dd'])

    # 按列序推断字段（epub.cnipa.gov.cn 典型列顺序）
    # 公开号 | 名称 | 申请人 | 公开日 | IPC | 类型
    COLUMN_ORDER = ['pub_no', 'title', 'applicant', 'pub_date', 'ipc', 'pat_type']
    for idx, cell in enumerate(cells[:len(COLUMN_ORDER)]):
        fname = COLUMN_ORDER[idx]
        val = _clean(cell.get_text())
        if fname == 'pub_no':
            m = _PAT_NO_RE.search(val)
            hit.pub_no = _norm_pat_no(m.group(1)) if m else val[:30]
            hit.url = _extract_detail_url(cell, hit.pub_no)
        elif fname == 'title':
            hit.title = val[:200]
            if not hit.url:
                hit.url = _extract_detail_url(cell, hit.pub_no)
        elif fname == 'applicant':
            hit.applicant = val[:100]
        elif fname == 'pub_date':
            dm = _DATE_RE.search(val)
            hit.pub_date = dm.group(1) if dm else val[:20]
        elif fname == 'ipc':
            im = _IPC_RE.search(val)
            hit.ipc = im.group(1) if im else val[:30]
        elif fname == 'pat_type':
            hit.pat_type = val[:20]

    # 尝试用标签名解析（dl/dt/dd 结构）
    if not hit.pub_no:
        for dt in row.find_all('dt'):
            fname = _field_from_label(_clean(dt.get_text()))
            if fname:
                dd = dt.find_next_sibling('dd')
                val = _clean(dd.get_text()) if dd else ""
                if fname == 'pub_no':
                    m = _PAT_NO_RE.search(val)
                    hit.pub_no = _norm_pat_no(m.group(1)) if m else val[:30]
                elif fname == 'title':
                    hit.title = val[:200]
                elif fname == 'applicant':
                    hit.applicant = val[:100]
                elif fname == 'pub_date':
                    hit.pub_date = val[:20]
                elif fname == 'ipc':
                    hit.ipc = val[:30]

    return hit if hit.pub_no else None


def _parse_container(container: Tag) -> List[EpubSearchHit]:
    hits: List[EpubSearchHit] = []
    for sel in _LIST_ITEM_SELECTORS:
        items = container.select(sel)
        if not items:
            continue
        for item in items:
            text = item.get_text()
            if not _PAT_NO_RE.search(text):
                continue
            h = _parse_structured_row(item)
            if h:
                hits.append(h)
        if hits:
            return hits
    return hits


# ── 策略 2：按专利号锚定段落 ──────────────────────────────────────────────────

def _parse_by_patent_anchor(soup: BeautifulSoup) -> List[EpubSearchHit]:
    """找所有含专利号的最小块元素，从周围文本提取字段。"""
    hits: List[EpubSearchHit] = []
    seen = set()

    for el in soup.find_all(string=_PAT_NO_RE):
        m = _PAT_NO_RE.search(el)
        if not m:
            continue
        pub_no = _norm_pat_no(m.group(1))
        if pub_no in seen:
            continue
        seen.add(pub_no)

        # 向上找最近的行/列表项
        parent = el.parent
        for _ in range(5):
            if parent is None:
                break
            tag = parent.name if parent else ''
            if tag in ('tr', 'li', 'div', 'article', 'section', 'dl'):
                break
            parent = parent.parent

        if parent is None:
            continue

        block_text = _clean(parent.get_text())
        hit = EpubSearchHit(pub_no=pub_no)

        # 从周围文本中提取各字段（简单启发式）
        lines = [l.strip() for l in block_text.split('\n') if l.strip()]
        for line in lines:
            if pub_no in line.replace(' ', ''):
                continue
            if not hit.title and len(line) > 4 and not _DATE_RE.match(line) and not _IPC_RE.match(line):
                hit.title = line[:200]
            elif not hit.pub_date:
                dm = _DATE_RE.search(line)
                if dm:
                    hit.pub_date = dm.group(1)
            elif not hit.ipc:
                im = _IPC_RE.search(line)
                if im:
                    hit.ipc = im.group(1)

        hit.url = _extract_detail_url(parent, pub_no)
        hits.append(hit)

    return hits


# ── 策略 3：纯正则从全文提取 ──────────────────────────────────────────────────

def _parse_by_regex(html: str) -> List[EpubSearchHit]:
    seen = set()
    hits: List[EpubSearchHit] = []
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&\w+;', ' ', text)
    for m in _PAT_NO_RE.finditer(text):
        pub_no = _norm_pat_no(m.group(1))
        if pub_no in seen:
            continue
        seen.add(pub_no)
        ctx = text[max(0, m.start()-50): m.end()+200]
        dm = _DATE_RE.search(ctx)
        im = _IPC_RE.search(ctx)
        hits.append(EpubSearchHit(
            pub_no=pub_no,
            pub_date=dm.group(1) if dm else "",
            ipc=im.group(1) if im else "",
            url=f"{EPUB_BASE}/patent/{pub_no}",
        ))
    return hits


# ── 主入口 ────────────────────────────────────────────────────────────────────

def parse_search_result_html(html: str) -> List[EpubSearchHit]:
    """
    解析 epub.cnipa.gov.cn 搜索结果页 HTML，返回 EpubSearchHit 列表。
    对同一份 HTML 依次尝试三种策略，取第一个返回非空结果的。
    """
    if not html or not html.strip():
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 去掉 script/style 标签以减少干扰
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()

    # 策略 1：精确结构
    for sel in _RESULT_CONTAINERS:
        try:
            containers = soup.select(sel)
        except Exception:
            continue
        for container in containers:
            hits = _parse_container(container)
            if hits:
                return hits

    # 策略 2：专利号锚定
    hits = _parse_by_patent_anchor(soup)
    if hits:
        return hits

    # 策略 3：正则兜底
    return _parse_by_regex(html)


# ── CLI 自测 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json

    if len(sys.argv) < 2:
        print("Usage: python3 cnipa_epub_parse.py <result.html>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    html = open(path, encoding="utf-8", errors="replace").read()
    hits = parse_search_result_html(html)
    print(f"解析到 {len(hits)} 条结果", file=sys.stderr)
    print(json.dumps(hits_to_jsonable(hits), ensure_ascii=False, indent=2))
