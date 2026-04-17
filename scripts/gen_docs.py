"""Static-site generator for the Autonomous docs.

Reads:
  - docs/*.md and docs/guides/*.md  (handwritten guides)
  - the public classes listed in ``MANIFEST`` below (auto-generated API
    reference from introspection)

Emits a fully self-contained HTML tree under docs/_build/ with:
  - a shared left-hand navigation sidebar
  - anchors per class / method
  - syntax-highlighted-ish code blocks (monospace + background)
  - zero JavaScript, zero external fonts, zero network calls

Run:

    python scripts/gen_docs.py           # writes to docs/_build/
    python scripts/gen_docs.py --clean   # rm -rf docs/_build/ first

The generator is intentionally tiny — no Jinja, no Sphinx, no pdoc.
Plain stdlib plus a hand-rolled Markdown subset (headings, paragraphs,
fenced code, inline code, links, lists, tables) sufficient for the
guides we ship.
"""

from __future__ import annotations

import argparse
import html
import importlib
import inspect
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
BUILD = DOCS / "_build"
ASSETS = DOCS / "assets"
GUIDES = DOCS / "guides"

SITE_TITLE = "Autonomous"
SITE_TAGLINE = "ORM + utilities for containerized Python apps."

# Public classes to introspect. Each entry: (import_path, class_name).
# Order within the tuple controls the sidebar order under Reference.
MANIFEST: tuple[tuple[str, str], ...] = (
    ("autonomous.model.automodel", "AutoModel"),
    ("autonomous.model.autoattr", "StringAttr"),
    ("autonomous.model.autoattr", "IntAttr"),
    ("autonomous.model.autoattr", "FloatAttr"),
    ("autonomous.model.autoattr", "BoolAttr"),
    ("autonomous.model.autoattr", "DateTimeAttr"),
    ("autonomous.model.autoattr", "EmailAttr"),
    ("autonomous.model.autoattr", "ListAttr"),
    ("autonomous.model.autoattr", "DictAttr"),
    ("autonomous.model.autoattr", "ReferenceAttr"),
    ("autonomous.model.autoattr", "FileAttr"),
    ("autonomous.model.autoattr", "ImageAttr"),
    ("autonomous.model.autoattr", "EnumAttr"),
    ("autonomous.auth.autoauth", "AutoAuth"),
    ("autonomous.auth.user", "AutoUser"),
    ("autonomous.auth.google", "GoogleAuth"),
    ("autonomous.auth.github", "GithubAuth"),
    ("autonomous.storage.localstorage", "LocalStorage"),
    ("autonomous.storage.imagestorage", "ImageStorage"),
    ("autonomous.taskrunner.autotasks", "AutoTasks"),
    ("autonomous.web.response", "Response"),
    ("autonomous.web.session", "ContextSession"),
    ("autonomous.web.session", "SignedCookieSession"),
    ("autonomous.ai.models.local_model", "LocalAIModel"),
    ("autonomous.ai.models.gemini", "GeminiAIModel"),
    ("autonomous.ai.models.mock_model", "MockAIModel"),
    ("autonomous.ai.retry", "retry"),
)

GUIDE_PAGES: tuple[tuple[str, str], ...] = (
    ("quickstart", "Quickstart"),
    ("ormodel", "ORM — AutoModel"),
    ("auth", "Auth — AutoAuth"),
    ("storage", "Storage"),
    ("tasks", "Tasks — AutoTasks"),
    ("web", "Web layer"),
    ("ai", "AI adapters"),
)


# ---------------------------------------------------------------------------
# Markdown (very small subset)
# ---------------------------------------------------------------------------


_INLINE_CODE = re.compile(r"``(.+?)``|`([^`]+?)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITAL = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def _rewrite_link(target: str) -> str:
    """Rewrite a markdown link target so it works after build.

    - ``foo.md`` → ``foo.html`` (same directory)
    - ``guides/foo.md`` → ``guides/foo.html``
    - ``../MIGRATIONS.md`` → ``../MIGRATIONS.md`` (left alone — out of tree)
    - absolute URLs untouched
    - in-page anchors untouched
    """
    if target.startswith(("http://", "https://", "#", "mailto:")):
        return target
    if target.endswith(".md"):
        # Cross-reference inside the docs tree.
        if target.startswith("../"):
            return target
        return target[:-3] + ".html"
    return target


def _inline(md: str) -> str:
    """Apply inline markdown transforms and return safe HTML."""

    # escape first, then re-open the inline patterns we support.
    escaped = html.escape(md, quote=False)

    # ``code``
    def code_sub(m: re.Match[str]) -> str:
        body = m.group(1) or m.group(2)
        return f"<code>{body}</code>"

    escaped = _INLINE_CODE.sub(code_sub, escaped)

    # [text](target)
    def link_sub(m: re.Match[str]) -> str:
        text, target = m.group(1), _rewrite_link(m.group(2))
        return f'<a href="{html.escape(target, quote=True)}">{text}</a>'

    escaped = _LINK.sub(link_sub, escaped)

    # **bold** and *italic*
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITAL.sub(r"<em>\1</em>", escaped)

    return escaped


def markdown_to_html(text: str) -> str:
    """Convert a small Markdown subset to HTML.

    Supports: headings (#..####), paragraphs, fenced code (``` blocks
    with optional language tag), inline code, links, bold/italic,
    unordered lists (``- ``), ordered lists (``1. ``), pipe tables.
    That's it.
    """

    lines = text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Fenced code block
        if line.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # closing ```
            body = html.escape("\n".join(buf))
            out.append(f"<pre><code>{body}</code></pre>")
            continue

        # Heading
        if line.startswith("#"):
            level = 0
            while level < len(line) and line[level] == "#":
                level += 1
            level = min(level, 6)
            title = line[level:].strip()
            slug = _slug(title)
            out.append(
                f'<h{level} id="{slug}">'
                f'<a href="#{slug}" aria-hidden="true">#</a> '
                f"{_inline(title)}</h{level}>"
            )
            i += 1
            continue

        # Blank line
        if not line.strip():
            i += 1
            continue

        # Unordered list
        if line.lstrip().startswith("- "):
            out.append("<ul>")
            while i < n and lines[i].lstrip().startswith("- "):
                item = lines[i].lstrip()[2:]
                out.append(f"<li>{_inline(item)}</li>")
                i += 1
            out.append("</ul>")
            continue

        # Ordered list (1. ... ; 2. ... ; etc.)
        if re.match(r"^\s*\d+\.\s", line):
            out.append("<ol>")
            while i < n and re.match(r"^\s*\d+\.\s", lines[i]):
                item = re.sub(r"^\s*\d+\.\s", "", lines[i])
                out.append(f"<li>{_inline(item)}</li>")
                i += 1
            out.append("</ol>")
            continue

        # Pipe-style table (at least header + separator + one row)
        if line.lstrip().startswith("|") and i + 1 < n and re.match(
            r"^\s*\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|\s*$", lines[i + 1]
        ):
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2  # skip separator
            rows: list[list[str]] = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(
                    [c.strip() for c in lines[i].strip().strip("|").split("|")]
                )
                i += 1
            out.append("<table><thead><tr>")
            out.extend(f"<th>{_inline(c)}</th>" for c in header)
            out.append("</tr></thead><tbody>")
            for r in rows:
                out.append("<tr>")
                out.extend(f"<td>{_inline(c)}</td>" for c in r)
                out.append("</tr>")
            out.append("</tbody></table>")
            continue

        # Paragraph — coalesce consecutive non-blank non-special lines.
        buf = [line]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            buf.append(lines[i])
            i += 1
        out.append(f"<p>{_inline(' '.join(buf))}</p>")

    return "\n".join(out)


def _is_block_start(line: str) -> bool:
    return (
        line.startswith("#")
        or line.startswith("```")
        or line.lstrip().startswith("- ")
        or bool(re.match(r"^\s*\d+\.\s", line))
        or line.lstrip().startswith("|")
    )


# ---------------------------------------------------------------------------
# HTML page scaffolding
# ---------------------------------------------------------------------------


@dataclass
class NavLink:
    href: str
    label: str
    kind: str = "page"  # "page" | "method"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"


def _relpath(target: Path, here: Path) -> str:
    """Relative path from ``here`` (a file) to ``target`` (a file)."""
    return str(Path(*([".."] * (len(here.relative_to(BUILD).parts) - 1))) / target.relative_to(BUILD))


def _nav_section(title: str, links: Iterable[NavLink], current: str) -> str:
    items = []
    for link in links:
        cls = "current" if link.href == current else ""
        li_cls = f"class=\"{link.kind}\"" if link.kind != "page" else ""
        items.append(
            f'<li {li_cls}><a class="{cls}" href="{html.escape(link.href, quote=True)}">'
            f"{html.escape(link.label)}</a></li>"
        )
    body = "".join(items)
    header = f"<h2>{html.escape(title)}</h2>" if title else ""
    return f"{header}<ul>{body}</ul>"


def render_page(
    title: str,
    body_html: str,
    nav_html: str,
    assets_href: str,
    root_href: str,
    breadcrumbs: str = "",
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} — {html.escape(SITE_TITLE)}</title>
  <link rel="stylesheet" href="{html.escape(assets_href, quote=True)}/style.css">
</head>
<body>
  <div class="layout">
    <nav class="sidebar">
      <h1><a href="{html.escape(root_href, quote=True)}">{html.escape(SITE_TITLE)}</a></h1>
      <p class="tagline">{html.escape(SITE_TAGLINE)}</p>
      {nav_html}
    </nav>
    <main>
      {breadcrumbs}
      {body_html}
      <footer>
        Generated by <code>scripts/gen_docs.py</code>. Edit the sources
        under <code>docs/</code> and re-run <code>make docs</code>.
      </footer>
    </main>
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Python introspection
# ---------------------------------------------------------------------------


def _public_methods(cls: type) -> list[tuple[str, Callable]]:
    """Return methods defined directly on ``cls`` (not inherited).

    Walks ``cls.__dict__`` rather than ``inspect.getmembers`` so we
    don't trigger data descriptors (e.g. the QuerySet manager on
    ``AutoModel`` which opens a MongoDB connection on read).
    """
    out: list[tuple[str, Callable]] = []
    for name, raw in cls.__dict__.items():
        if name.startswith("_"):
            continue
        if isinstance(raw, classmethod):
            func = raw.__func__
        elif isinstance(raw, staticmethod):
            func = raw.__func__
        elif inspect.isfunction(raw):
            func = raw
        else:
            continue
        out.append((name, func))
    out.sort()
    return out


def _format_signature(name: str, obj) -> str:
    try:
        sig = inspect.signature(obj)
        return f"{name}{sig}"
    except (TypeError, ValueError):
        return f"{name}(...)"


def _render_docstring(doc: str | None) -> str:
    if not doc:
        return "<p><em>No description.</em></p>"
    cleaned = inspect.cleandoc(doc)
    return markdown_to_html(cleaned)


def render_api_reference(
    module_path: str, name: str, nav_html: str, assets_href: str
) -> tuple[str, list[str]]:
    """Return (html_body, list_of_method_names) for an API target.

    Returns a "not installed" stub if ``module_path`` can't be
    imported (optional-dependency case). Re-raises anything else so
    genuinely broken imports surface.
    """
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        return _render_missing(module_path, name, str(exc)), []
    obj = getattr(module, name)

    if inspect.isclass(obj):
        return _render_class(obj, module_path, nav_html, assets_href)
    if inspect.isfunction(obj):
        return _render_function(obj, module_path, name)
    raise TypeError(f"Unsupported reference target: {module_path}.{name}")


def _render_missing(module_path: str, name: str, reason: str) -> str:
    return (
        f"<h1>{html.escape(name)}</h1>"
        f'<p class="breadcrumbs"><a href="index.html">Reference</a></p>'
        f'<div class="api-class">'
        f'<header><span class="kw">unavailable</span> '
        f'<span class="name">{html.escape(name)}</span>'
        f"  <small><code>{html.escape(module_path)}</code></small></header>"
        f'<div class="body">'
        f"<p>This reference target requires an optional dependency that "
        f"isn't installed in the environment that built these docs:</p>"
        f"<pre><code>{html.escape(reason)}</code></pre>"
        f"<p>Install the matching extra (see <a href=\"../guides/quickstart.html\">Quickstart</a>) "
        f"and re-run <code>make docs</code>.</p>"
        f"</div></div>"
    )


def _render_class(cls: type, module_path: str, nav_html: str, assets_href: str) -> tuple[str, list[str]]:
    header = (
        f'<header><span class="kw">class</span> '
        f'<span class="name">{html.escape(cls.__name__)}</span>'
        f"  <small><code>{html.escape(module_path)}.{html.escape(cls.__name__)}</code></small></header>"
    )
    body_parts = [header, '<div class="body">']
    body_parts.append(_render_docstring(cls.__doc__))

    method_names: list[str] = []
    methods = _public_methods(cls)
    if methods:
        body_parts.append("<h3>Methods</h3>")
        for name, obj in methods:
            method_names.append(name)
            slug = _slug(f"{cls.__name__}-{name}")
            sig = _format_signature(name, obj)
            body_parts.append(
                f'<div class="api-method">'
                f'<h4 id="{slug}"><span class="kw">def</span> '
                f"{html.escape(sig)}</h4>"
                f"{_render_docstring(obj.__doc__)}"
                f"</div>"
            )
    body_parts.append("</div>")
    page_body = (
        f'<h1>{html.escape(cls.__name__)}</h1>'
        f'<p class="breadcrumbs"><a href="index.html">Reference</a></p>'
        f'<div class="api-class">' + "".join(body_parts) + "</div>"
    )
    return page_body, method_names


def _render_function(fn, module_path: str, name: str) -> tuple[str, list[str]]:
    sig = _format_signature(name, fn)
    body = (
        f'<h1>{html.escape(name)}</h1>'
        f'<p class="breadcrumbs"><a href="index.html">Reference</a></p>'
        f'<div class="api-class">'
        f'<header><span class="kw">def</span> '
        f'<span class="name">{html.escape(sig)}</span>'
        f"  <small><code>{html.escape(module_path)}.{html.escape(name)}</code></small></header>"
        f'<div class="body">{_render_docstring(fn.__doc__)}</div>'
        f"</div>"
    )
    return body, []


# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------


def build(clean: bool = False) -> Path:
    if clean and BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "guides").mkdir(exist_ok=True)
    (BUILD / "reference").mkdir(exist_ok=True)

    # Copy assets
    target_assets = BUILD / "assets"
    if target_assets.exists():
        shutil.rmtree(target_assets)
    shutil.copytree(ASSETS, target_assets)

    # --- Build the nav shared by every page (per depth) --------------------
    guide_links = [
        NavLink(href=f"guides/{slug}.html", label=label)
        for slug, label in GUIDE_PAGES
    ]

    # Reference nav is keyed by class/name.
    ref_entries: list[tuple[str, str, list[str]]] = []  # (slug, display, methods)
    for module_path, name in MANIFEST:
        ref_entries.append((_slug(name), name, []))
    ref_links = [
        NavLink(href=f"reference/{slug}.html", label=label)
        for slug, label, _ in ref_entries
    ]

    def _nav(depth: int, current: str) -> str:
        """Render the nav with links relative to a page at ``depth``.

        depth = 0 → index.html
        depth = 1 → guides/x.html, reference/x.html
        """
        prefix = "" if depth == 0 else "../"

        def adjust(link: NavLink) -> NavLink:
            return NavLink(href=prefix + link.href, label=link.label, kind=link.kind)

        overview = NavLink(href=f"{prefix}index.html", label="Overview")
        guides = [overview] + [adjust(l) for l in guide_links]
        refs = [adjust(l) for l in ref_links]

        return (
            _nav_section("Guides", guides, current)
            + _nav_section("Reference", refs, current)
        )

    def _assets_href(depth: int) -> str:
        return "assets" if depth == 0 else "../assets"

    def _root_href(depth: int) -> str:
        return "index.html" if depth == 0 else "../index.html"

    # --- Landing page -------------------------------------------------------
    index_md = (DOCS / "index.md").read_text(encoding="utf-8")
    index_html = markdown_to_html(index_md)
    (BUILD / "index.html").write_text(
        render_page(
            "Home",
            index_html,
            _nav(0, "index.html"),
            _assets_href(0),
            _root_href(0),
        ),
        encoding="utf-8",
    )

    # --- Guide pages --------------------------------------------------------
    for slug, label in GUIDE_PAGES:
        src = GUIDES / f"{slug}.md"
        if not src.exists():
            continue
        body = markdown_to_html(src.read_text(encoding="utf-8"))
        page = render_page(
            label,
            body,
            _nav(1, f"guides/{slug}.html"),
            _assets_href(1),
            _root_href(1),
        )
        (BUILD / "guides" / f"{slug}.html").write_text(page, encoding="utf-8")

    # --- Reference pages ----------------------------------------------------
    ref_index_items = []
    for module_path, name in MANIFEST:
        slug = _slug(name)
        body_html, _ = render_api_reference(module_path, name, "", _assets_href(1))
        page = render_page(
            name,
            body_html,
            _nav(1, f"reference/{slug}.html"),
            _assets_href(1),
            _root_href(1),
        )
        (BUILD / "reference" / f"{slug}.html").write_text(page, encoding="utf-8")
        ref_index_items.append(
            f'<li><a href="{html.escape(slug, quote=True)}.html">{html.escape(name)}</a> '
            f"— <code>{html.escape(module_path)}</code></li>"
        )

    ref_index_html = (
        "<h1>API Reference</h1>"
        '<p class="breadcrumbs"><a href="../index.html">Home</a></p>'
        "<ul>" + "".join(ref_index_items) + "</ul>"
    )
    (BUILD / "reference" / "index.html").write_text(
        render_page(
            "Reference",
            ref_index_html,
            _nav(1, "reference/index.html"),
            _assets_href(1),
            _root_href(1),
        ),
        encoding="utf-8",
    )

    return BUILD


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="rm -rf docs/_build first")
    args = parser.parse_args(argv)
    output = build(clean=args.clean)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
