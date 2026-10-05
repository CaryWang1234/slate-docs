#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SLATE 文档站生成器 · 零依赖（只用 Python 标准库）

把 content/*.md 渲染成 docs/ 下的静态站点：左侧分组导航、面包屑、右侧本页目录、
客户端搜索、明暗主题、代码复制、翻页。产物可直接部署到 GitHub Pages。

用法：
    python build.py             # 生成到 docs/
    python build.py --check     # 只校验 frontmatter 与站内链接，不写文件
    python build.py --clean     # 生成前清空输出目录
    python build.py --out site  # 换输出目录
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "content"
THEME_DIR = ROOT / "theme"
DEFAULT_OUT = ROOT / "docs"

try:  # Windows 控制台默认 GBK，中文与 ✓ 会直接抛 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

CALLOUT_LABELS = {
    "note": ("说明", '<circle cx="10" cy="10" r="7.2"/><path d="M10 9v4.6M10 6.6v.1"/>'),
    "tip": ("提示", '<circle cx="10" cy="10" r="7.2"/><path d="M10 13.4V9M10 6.6v.6"/><path d="M7.6 12.4h4.8"/>'),
    "warning": ("注意", '<path d="M10 3.4 17.4 16.6H2.6Z"/><path d="M10 8.2v3.4M10 14v.1"/>'),
    "danger": ("警告", '<circle cx="10" cy="10" r="7.2"/><path d="M10 6.4v4.2M10 13.4v.2"/>'),
}

LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
HEAD_RE = re.compile(r"^(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^\s*```+\s*([A-Za-z0-9_+#.-]*)\s*$")
DIRECTIVE_RE = re.compile(r"^:::(\w+)\s*(.*)$")
FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


# ── frontmatter ────────────────────────────────────────────────

def split_front(text: str) -> tuple[dict, str]:
    m = FRONT_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[m.end():]


def plain_text(md: str) -> str:
    s = re.sub(r"```.*?```", " ", md, flags=re.S)
    s = re.sub(r"^:::.*$", " ", s, flags=re.M)
    s = re.sub(r"^\s{0,3}#{1,6}\s*", " ", s, flags=re.M)
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_`>|]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# ── 行内渲染 ───────────────────────────────────────────────────

def slugify(text: str, used: dict[str, int]) -> str:
    plain = re.sub(r"<[^>]+>", "", text)
    slug = re.sub(r"\s+", "-", plain.strip().lower())
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "", slug)
    slug = slug.strip("-") or "section"
    if slug in used:
        used[slug] += 1
        slug = f"{slug}-{used[slug]}"
    else:
        used[slug] = 0
    return slug


def map_href(href: str) -> tuple[str, bool]:
    """把 Markdown 源链接改写成站点链接；返回 (href, 是否外链)。"""
    if re.match(r"^(https?:|mailto:|tel:)", href):
        return href, True
    if href.startswith("#"):
        return href, False
    base, sep, frag = href.partition("#")
    if base.endswith(".md"):
        base = base[:-3] + ".html"
    elif base.endswith("/"):
        base += "index.html"
    elif not base:
        base = ""
    return base + (sep + frag if sep else ""), False


def render_inline(text: str) -> str:
    codes: list[str] = []

    def stash(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    out = html.escape(text, quote=False)

    def img(m: re.Match) -> str:
        alt = html.escape(m.group(1), quote=True)
        src = html.escape(map_href(m.group(2))[0], quote=True)
        return f'<img src="{src}" alt="{alt}" loading="lazy">'

    def link(m: re.Match) -> str:
        label = m.group(1)
        href, external = map_href(m.group(2).strip())
        attrs = ' target="_blank" rel="noopener"' if external else ""
        return f'<a href="{html.escape(href, quote=True)}"{attrs}>{label}</a>'

    out = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", img, out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", out)

    for i, code in enumerate(codes):
        out = out.replace(f"\x00{i}\x00", f"<code>{html.escape(code, quote=False)}</code>")
    return out


# ── 块级渲染 ───────────────────────────────────────────────────

def render_code_block(lang: str, body: str) -> str:
    label = lang or "text"
    return (
        '<div class="code-block">'
        f'<div class="code-head"><span class="code-lang">{html.escape(label)}</span>'
        '<button class="code-copy" type="button" data-copy>复制</button></div>'
        f'<pre><code class="language-{html.escape(label)}">{html.escape(body, quote=False)}</code></pre>'
        "</div>"
    )


def render_callout(kind: str, title: str, inner: str) -> str:
    label, icon = CALLOUT_LABELS.get(kind, CALLOUT_LABELS["note"])
    head = title or label
    return (
        f'<div class="callout callout-{kind if kind in CALLOUT_LABELS else "note"}">'
        f'<div class="callout-head"><svg viewBox="0 0 20 20" aria-hidden="true">{icon}</svg>'
        f"<span>{render_inline(head)}</span></div>"
        f'<div class="callout-body">{inner}</div>'
        "</div>"
    )


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def cell_attr(aligns: list[str], i: int) -> str:
    if i < len(aligns) and aligns[i]:
        return f' style="text-align:{aligns[i]}"'
    return ""


def render_table(rows: list[list[str]], aligns: list[str]) -> str:
    head, *body = rows
    ths = "".join(f"<th{cell_attr(aligns, i)}>{render_inline(c)}</th>" for i, c in enumerate(head))
    trs = []
    for row in body:
        tds = "".join(f"<td{cell_attr(aligns, i)}>{render_inline(c)}</td>" for i, c in enumerate(row))
        trs.append(f"<tr>{tds}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{ths}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def parse_list_block(lines: list[str], start: int) -> tuple[list[str], int]:
    block: list[str] = []
    i = start
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and LIST_RE.match(lines[j]):
                i = j
                continue
            break
        if LIST_RE.match(raw) or raw.startswith(("  ", "\t")):
            block.append(raw)
            i += 1
        else:
            break
    return block, i


def build_list_tree(block: list[str]) -> list[dict]:
    root: dict = {"children": []}
    stack: list[tuple[int, dict]] = [(-1, root)]
    last: dict | None = None
    for raw in block:
        if not raw.strip():
            continue
        m = LIST_RE.match(raw)
        if m:
            indent = len(m.group(1).expandtabs(4))
            node = {"ordered": m.group(2)[0].isdigit(), "text": [m.group(3)], "children": []}
            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()
            stack[-1][1]["children"].append(node)
            stack.append((indent, node))
            last = node
        elif last is not None:
            last["text"].append(raw.strip())
            last["text"].append("")
    for node in root["children"]:
        node.setdefault("children", [])
    return root["children"]


def render_list_nodes(nodes: list[dict]) -> str:
    out: list[str] = []
    i = 0
    while i < len(nodes):
        ordered = nodes[i]["ordered"]
        group = []
        while i < len(nodes) and nodes[i]["ordered"] == ordered:
            group.append(nodes[i])
            i += 1
        items = []
        for node in group:
            text = " ".join([p for p in node["text"] if p]).strip()
            inner = render_inline(text)
            if node.get("children"):
                inner += render_list_nodes(node["children"])
            items.append(f"<li>{inner}</li>")
        tag = "ol" if ordered else "ul"
        out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
    return "".join(out)


def is_table_start(lines: list[str], i: int) -> bool:
    if i + 1 >= len(lines) or "|" not in lines[i]:
        return False
    nxt = lines[i + 1].strip()
    return bool(re.match(r"^\|?[\s:\-|]+\|[\s:\-|]*$", nxt)) and "-" in nxt


def render_blocks(lines: list[str], toc: list[dict] | None, used_ids: dict[str, int]) -> str:
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        raw = lines[i]
        stripped = raw.strip()

        if not stripped:
            i += 1
            continue

        fence = FENCE_RE.match(raw)
        if fence:
            lang = fence.group(1)
            i += 1
            buf = []
            while i < n and not FENCE_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append(render_code_block(lang, "\n".join(buf)))
            continue

        directive = DIRECTIVE_RE.match(stripped)
        if directive:
            kind = directive.group(1).lower()
            title = directive.group(2).strip()
            i += 1
            buf = []
            while i < n and lines[i].strip() != ":::":
                buf.append(lines[i])
                i += 1
            i += 1
            inner = render_blocks(buf, None, used_ids)
            out.append(render_callout(kind, title, inner))
            continue

        head = HEAD_RE.match(stripped)
        if head:
            level = len(head.group(1))
            text = head.group(2).strip()
            hid = slugify(text, used_ids)
            if toc is not None and 2 <= level <= 3:
                toc.append({"id": hid, "text": re.sub(r"<[^>]+>", "", text), "level": level})
            cls = ' class="doc-title"' if level == 1 else ""
            out.append(
                f'<h{level} id="{hid}"{cls}>'
                f'<a class="anchor" href="#{hid}" aria-hidden="true">#</a>{render_inline(text)}</h{level}>'
            )
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            out.append("<hr>")
            i += 1
            continue

        if is_table_start(lines, i):
            rows = [split_row(lines[i])]
            aligns = []
            for cell in split_row(lines[i + 1]):
                left, right = cell.startswith(":"), cell.endswith(":")
                aligns.append("center" if left and right else "right" if right else "left" if left else "")
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            out.append(render_table(rows, aligns))
            continue

        if LIST_RE.match(raw):
            block, i = parse_list_block(lines, i)
            out.append(render_list_nodes(build_list_tree(block)))
            continue

        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{render_blocks(buf, None, used_ids)}</blockquote>")
            continue

        buf = []
        while i < n:
            cur = lines[i]
            if not cur.strip():
                break
            if FENCE_RE.match(cur) or HEAD_RE.match(cur.strip()) or LIST_RE.match(cur):
                break
            if DIRECTIVE_RE.match(cur.strip()) or cur.strip().startswith(">"):
                break
            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", cur.strip()) or is_table_start(lines, i):
                break
            buf.append(cur.strip())
            i += 1
        if buf:
            out.append(f"<p>{render_inline(' '.join(buf))}</p>")

    return "\n".join(out)


# ── 站点装配 ───────────────────────────────────────────────────

class Page:
    def __init__(self, meta: dict, body: str, source: Path):
        self.source = source
        self.slug = source.stem
        self.title = meta.get("title") or self.slug
        self.description = meta.get("description", "")
        self.section = meta.get("section", "文档")
        try:
            self.order = int(meta.get("order", "999"))
        except ValueError:
            self.order = 999
        self.toc: list[dict] = []
        self.content = render_blocks(body.splitlines(), self.toc, {})
        self.text = plain_text(body)
        self.href = f"./{self.slug}.html"
        self.warnings: list[str] = []


def load_pages() -> list[Page]:
    pages = []
    for path in sorted(CONTENT_DIR.glob("*.md")):
        meta, body = split_front(path.read_text(encoding="utf-8"))
        page = Page(meta, body, path)
        if not meta:
            page.warnings.append(f"{path.name}: 缺少 frontmatter")
        for key in ("title", "description", "section"):
            if not meta.get(key):
                page.warnings.append(f"{path.name}: frontmatter 缺少 {key}")
        if not meta.get("order"):
            page.warnings.append(f"{path.name}: frontmatter 缺少 order")
        pages.append(page)
    pages.sort(key=lambda p: (p.order, p.slug))
    return pages


def build_sidebar(pages: list[Page], current: Page | None) -> str:
    groups: list[tuple[str, list[Page]]] = []
    for page in pages:
        if groups and groups[-1][0] == page.section:
            groups[-1][1].append(page)
        else:
            groups.append((page.section, [page]))

    chunks = []
    for name, items in groups:
        links = []
        for page in items:
            active = " active" if current and page.slug == current.slug else ""
            links.append(f'<li><a class="nav-link{active}" href="{page.href}">{html.escape(page.title)}</a></li>')
        chunks.append(
            '<div class="nav-group">'
            f'<div class="nav-group-title">{html.escape(name)}</div>'
            f'<ul class="nav-list">{"".join(links)}</ul>'
            "</div>"
        )
    return "".join(chunks)


def build_breadcrumbs(page: Page) -> str:
    return (
        '<a href="./index.html">文档</a>'
        '<span class="sep">/</span>'
        f'<span>{html.escape(page.section)}</span>'
        '<span class="sep">/</span>'
        f'<span class="current">{html.escape(page.title)}</span>'
    )


def build_toc(page: Page) -> str:
    if not page.toc:
        return '<div class="toc-title">本页目录</div><div class="toc-empty">这页没有小节</div>'
    items = "".join(
        f'<li class="lv{row["level"]}"><a href="#{row["id"]}">{html.escape(row["text"])}</a></li>'
        for row in page.toc
    )
    return f'<div class="toc-title">本页目录</div><ul class="toc-list">{items}</ul>'


def build_pager(index: int, pages: list[Page]) -> str:
    prev_page = pages[index - 1] if index > 0 else None
    next_page = pages[index + 1] if index + 1 < len(pages) else None

    def cell(page: Page | None, direction: str) -> str:
        if not page:
            return '<span class="empty"></span>'
        label = "上一篇" if direction == "prev" else "下一篇"
        return (
            f'<a class="{direction}" href="{page.href}">'
            f'<span class="dir">{label}</span>'
            f'<span class="ttl">{html.escape(page.title)}</span></a>'
        )

    return cell(prev_page, "prev") + cell(next_page, "next")


def build_home(pages: list[Page]) -> str:
    groups: list[tuple[str, list[Page]]] = []
    for page in pages:
        if groups and groups[-1][0] == page.section:
            groups[-1][1].append(page)
        else:
            groups.append((page.section, [page]))

    blocks = []
    for name, items in groups:
        cards = "".join(
            f'<a class="card" href="{page.href}">'
            f'<span class="c-index">{page.order:02d}</span>'
            f'<span class="c-title">{html.escape(page.title)}</span>'
            f'<span class="c-desc">{html.escape(page.description)}</span></a>'
            for page in items
        )
        blocks.append(
            f'<section class="home-section"><h2>{html.escape(name)}</h2>'
            f'<div class="card-grid">{cards}</div></section>'
        )

    template = (THEME_DIR / "home.html").read_text(encoding="utf-8")
    return template.replace("{{CARDS}}", "".join(blocks)).replace("{{COUNT}}", str(len(pages)))


def search_index_js(pages: list[Page]) -> str:
    data = [
        {
            "t": page.title,
            "u": page.href,
            "s": page.section,
            "h": [row["text"] for row in page.toc],
            "x": page.text,
        }
        for page in pages
    ]
    return "window.SLATE_DOCS_INDEX = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"


def check_links(pages: list[Page]) -> list[str]:
    known = {page.slug: page for page in pages}
    problems = []
    pattern = re.compile(r"\]\(([^)\s]+\.md)(#[^)\s]*)?\)")
    for page in pages:
        body = page.source.read_text(encoding="utf-8")
        for match in pattern.finditer(body):
            target = match.group(1)
            name = Path(target).name
            if Path(target).stem not in known:
                problems.append(f"{page.source.name} → 链接指向不存在的页面：{target}")
                continue
            anchor = (match.group(2) or "").lstrip("#")
            if anchor:
                target_page = known[Path(target).stem]
                ids = {row["id"] for row in target_page.toc}
                if anchor not in ids:
                    problems.append(
                        f"{page.source.name} → 锚点不存在：{name}#{anchor}（{target_page.title}）"
                    )
    return problems


def render_site(pages: list[Page], out_dir: Path) -> int:
    layout = (THEME_DIR / "layout.html").read_text(encoding="utf-8")
    icon_src = THEME_DIR / "icon.png"
    icon_href = "./assets/icon.png" if icon_src.exists() else ""
    assets_dir = out_dir / "assets"

    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(THEME_DIR / "docs.css", assets_dir / "docs.css")
    shutil.copy2(THEME_DIR / "docs.js", assets_dir / "docs.js")
    (assets_dir / "search-index.js").write_text(search_index_js(pages), encoding="utf-8", newline="\n")
    if icon_src.exists():
        shutil.copy2(icon_src, assets_dir / "icon.png")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    def render(page_title: str, description: str, body_attrs: str, sidebar: str,
               crumbs: str, content: str, pager: str, toc: str) -> str:
        return (
            layout.replace("{{PAGE_TITLE}}", html.escape(page_title))
            .replace("{{DESCRIPTION}}", html.escape(description, quote=True))
            .replace("{{ICON}}", icon_href)
            .replace("{{BODY_ATTRS}}", body_attrs)
            .replace("{{SIDEBAR}}", sidebar)
            .replace("{{BREADCRUMBS}}", crumbs)
            .replace("{{CONTENT}}", content)
            .replace("{{PAGER}}", pager)
            .replace("{{TOC}}", toc)
        )

    written = 0
    for index, page in enumerate(pages):
        heading = f'<h1 class="doc-title" id="top">{render_inline(page.title)}</h1>'
        out = render(
            f"{page.title} · SLATE 文档",
            page.description,
            f'data-page="{page.slug}"',
            build_sidebar(pages, page),
            build_breadcrumbs(page),
            heading + "\n" + page.content,
            build_pager(index, pages),
            build_toc(page),
        )
        (out_dir / f"{page.slug}.html").write_text(out, encoding="utf-8", newline="\n")
        written += 1

    home = render(
        "SLATE 文档 · 本地 AI 协作调度台",
        "SLATE（砚）面向使用者的完整文档：安装、对话、Agent Autopilot、目标模式、磨墨、工具与技能、团队与工作流、项目与数据、移动端遥控与设置。",
        'data-layout="home"',
        build_sidebar(pages, None),
        "",
        build_home(pages),
        "",
        "",
    )
    (out_dir / "index.html").write_text(home, encoding="utf-8", newline="\n")
    written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 SLATE 文档站")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    parser.add_argument("--clean", action="store_true", help="生成前清空输出目录")
    parser.add_argument("--out", default="docs", help="输出目录，默认 docs/（GitHub Pages 认 main 分支的 /docs）")
    args = parser.parse_args()

    if not CONTENT_DIR.is_dir():
        print(f"× 找不到内容目录：{CONTENT_DIR}", file=sys.stderr)
        return 1

    pages = load_pages()
    if not pages:
        print("× content/ 下没有 .md 文件", file=sys.stderr)
        return 1

    warnings = [w for page in pages for w in page.warnings]
    problems = check_links(pages)

    print(f"· 读取 {len(pages)} 个页面")
    for item in warnings:
        print(f"  ! {item}")
    for item in problems:
        print(f"  ! {item}")

    if args.check:
        print("× 校验失败" if (warnings or problems) else "✓ 校验通过")
        return 1 if (warnings or problems) else 0

    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)

    written = render_site(pages, out_dir)
    total_kb = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file()) / 1024
    print(f"✓ 生成 {written} 个页面 → {out_dir}（{total_kb:.0f} KB）")
    if warnings or problems:
        print("  有告警，请看上面列出的条目")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
