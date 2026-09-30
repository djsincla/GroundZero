#!/usr/bin/env bash
#!/usr/bin/env python3
"""
Dev & build script: reads project documentation Markdown files (README.md,
docs/*.md, ARCHITECTURE.md, CHANGELOG.md), converts them to clean HTML, and
bundles them as a python dictionary in groundzero/web/docs_data.py.

Run automatically during build (build-web.sh / build-web.bat) or manually:
    python tools/bundle_docs.py

Uses standard library only (html, re, os, json, sys).
"""

import html
import json
import os
import re
import sys
from typing import Dict, List

# Ensure stdout/stderr handles Unicode safely on Windows CMD / PowerShell (CP1252)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
OUT_PATH = os.path.join(PROJECT_ROOT, "groundzero", "web", "docs_data.py")

DOC_FILES = [
    {
        "id": "readme",
        "title": "User Guide (README)",
        "icon": "📖",
        "rel_path": "README.md",
    },
    {
        "id": "install",
        "title": "Installation Guide",
        "icon": "🚀",
        "rel_path": "docs/INSTALL.md",
    },
    {
        "id": "security_architecture",
        "title": "Security Architecture",
        "icon": "🛡️",
        "rel_path": "docs/SECURITY_ARCHITECTURE.md",
    },
    {
        "id": "credential_vault",
        "title": "Credential Vault Guide",
        "icon": "🔐",
        "rel_path": "docs/CREDENTIAL_VAULT.md",
    },
    {
        "id": "remote_jump_host",
        "title": "Remote Jump Host Guide (Experimental)",
        "icon": "🌐",
        "rel_path": "docs/REMOTE_JUMP_HOST_GUIDE.md",
    },
    {
        "id": "architecture",
        "title": "Architecture Overview",
        "icon": "🏗️",
        "rel_path": "ARCHITECTURE.md",
    },
    {
        "id": "oem_reference",
        "title": "OEM Reference Guide",
        "icon": "🔧",
        "rel_path": "docs/OEM_REFERENCE.md",
    },
    {
        "id": "adding_oem",
        "title": "Adding OEM Support",
        "icon": "🧩",
        "rel_path": "docs/adding-oem-support.md",
    },
    {
        "id": "inventory_reference",
        "title": "Inventory Reference Guide",
        "icon": "📋",
        "rel_path": "docs/INVENTORY_REFERENCE.md",
    },
    {
        "id": "user_guide_reference",
        "title": "User Guide & Reference",
        "icon": "📚",
        "rel_path": "docs/USER_GUIDE_REFERENCE.md",
    },
    {
        "id": "management_pack",
        "title": "Management Pack Guide",
        "icon": "📦",
        "rel_path": "docs/MANAGEMENT_PACK_GUIDE.md",
    },
    {
        "id": "mp_metric_reference",
        "title": "MP Metric Reference",
        "icon": "📊",
        "rel_path": "docs/MP_METRIC_REFERENCE.md",
    },
    {
        "id": "infographic",
        "title": "Readiness Infographic & Presentation Deck",
        "icon": "📈",
        "rel_path": "docs/INFOGRAPHIC.md",
    },
    {
        "id": "customer_deliverable_sbom",
        "title": "Software Bill of Materials (SBOM)",
        "icon": "🧾",
        "rel_path": "docs/CUSTOMER_DELIVERABLE_SBOM.md",
    },
    {
        "id": "changelog",
        "title": "Changelog & History",
        "icon": "📋",
        "rel_path": "CHANGELOG.md",
    },
]


def slugify(text: str) -> str:
    """Convert text into clean header anchor ID."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s_-]+", "-", text).strip("-")


def inline_markdown(text: str) -> str:
    """Convert inline Markdown syntax (code, links, bold, italic) into HTML."""
    # Placeholders for inline code to avoid double-processing
    code_tokens: List[str] = []

    def save_code(m: re.Match) -> str:
        code_content = html.escape(m.group(1))
        code_tokens.append(f"<code>{code_content}</code>")
        return f"@@CODETOKEN{len(code_tokens)-1}@@"

    text = re.sub(r"`([^`]+)`", save_code, text)

    # HTML escape remaining text
    text = html.escape(text)

    # Images: ![alt](url)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        r'<img src="\2" alt="\1" class="docs-img">',
        text,
    )

    # Links: [text](url) -> tokenize to avoid interference with bold/italic underscores
    link_tokens: List[str] = []

    def render_link(m: re.Match) -> str:
        label = m.group(1)
        url = m.group(2)
        # Internal doc links like docs/INSTALL.md or #header
        if url.startswith("#"):
            rendered = f'<a href="{url}">{label}</a>'
        elif url.endswith(".md") or ".md#" in url:
            # Map .md cross references if possible
            target_id = ""
            if "INSTALL.md" in url:
                target_id = "install"
            elif "SECURITY_ARCHITECTURE.md" in url or "SECURITY_ASSURANCE.md" in url:
                target_id = "security_architecture"
            elif "CREDENTIAL_VAULT.md" in url:
                target_id = "credential_vault"
            elif "ARCHITECTURE.md" in url:
                target_id = "architecture"
            elif "OEM_REFERENCE.md" in url:
                target_id = "oem_reference"
            elif "adding-oem-support.md" in url:
                target_id = "adding_oem"
            elif "INVENTORY_REFERENCE.md" in url:
                target_id = "inventory_reference"
            elif "USER_GUIDE_REFERENCE.md" in url:
                target_id = "user_guide_reference"
            elif "MANAGEMENT_PACK_GUIDE.md" in url:
                target_id = "management_pack"
            elif "MP_METRIC_REFERENCE.md" in url:
                target_id = "mp_metric_reference"
            elif "INFOGRAPHIC.md" in url or "infographic.html" in url:
                target_id = "infographic"
            elif "RELEASE_WORKFLOW_GUIDE.md" in url or "README.md" in url:
                target_id = "readme"
            elif "CHANGELOG.md" in url:
                target_id = "changelog"

            if target_id:
                anchor = ""
                if "#" in url:
                    anchor = "#" + url.split("#", 1)[1]
                rendered = f'<a href="/docs/{target_id}{anchor}">{label}</a>'
            else:
                rendered = f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'
        else:
            rendered = f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'

        idx = len(link_tokens)
        link_tokens.append(rendered)
        return f"@@LINKTOKEN{idx}@@"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", render_link, text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)

    # Italic: *text* or _text_
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+)_", r"<em>\1</em>", text)

    # Restore links
    for i, tok in enumerate(link_tokens):
        text = text.replace(f"@@LINKTOKEN{i}@@", tok)

    # Restore inline code tokens
    for i, tok in enumerate(code_tokens):
        text = text.replace(f"@@CODETOKEN{i}@@", tok)

    return text


def markdown_to_html(md_text: str) -> str:
    """Convert full Markdown string to HTML."""
    lines = md_text.replace("\r\n", "\n").split("\n")
    out: List[str] = []

    in_code_block = False
    code_lang = ""
    code_lines: List[str] = []

    in_list = False
    list_type = ""  # "ul" or "ol"

    in_blockquote = False
    quote_lines: List[str] = []

    in_table = False
    table_rows: List[List[str]] = []

    def flush_list():
        nonlocal in_list, list_type
        if in_list:
            out.append(f"</{list_type}>")
            in_list = False
            list_type = ""

    def flush_quote():
        nonlocal in_blockquote, quote_lines
        if in_blockquote:
            quote_text = "<br>".join(inline_markdown(l) for l in quote_lines)
            out.append(f"<blockquote>{quote_text}</blockquote>")
            in_blockquote = False
            quote_lines = []

    def flush_table():
        nonlocal in_table, table_rows
        if in_table and table_rows:
            html_table = ['<div class="docs-table-wrap"><table class="docs-table">']
            # Assume row 0 is header, row 1 is separator (if exists)
            if len(table_rows) >= 2 and all(re.match(r"^:?-+:?$", cell.strip()) for cell in table_rows[1] if cell.strip()):
                header_row = table_rows[0]
                body_rows = table_rows[2:]
            else:
                header_row = []
                body_rows = table_rows

            if header_row:
                html_table.append("<thead><tr>")
                for cell in header_row:
                    html_table.append(f"<th>{inline_markdown(cell.strip())}</th>")
                html_table.append("</tr></thead>")

            if body_rows:
                html_table.append("<tbody>")
                for row in body_rows:
                    html_table.append("<tr>")
                    for cell in row:
                        html_table.append(f"<td>{inline_markdown(cell.strip())}</td>")
                    html_table.append("</tr>")
                html_table.append("</tbody>")

            html_table.append("</table></div>")
            out.append("\n".join(html_table))
            in_table = False
            table_rows = []

    for line in lines:
        stripped = line.strip()

        # Code blocks
        if stripped.startswith("```"):
            if in_code_block:
                escaped_code = html.escape("\n".join(code_lines))
                lang_attr = f' class="language-{html.escape(code_lang)}"' if code_lang else ''
                out.append(f'<pre><code{lang_attr}>{escaped_code}</code></pre>')
                in_code_block = False
                code_lang = ""
                code_lines = []
            else:
                flush_list()
                flush_quote()
                flush_table()
                in_code_block = True
                code_lang = stripped[3:].strip()
                code_lines = []
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # Tables
        if "|" in line and not stripped.startswith(">"):
            parts = [c for c in line.strip().split("|")]
            # Strip leading/trailing empty cells from outer pipes
            if parts and parts[0] == "":
                parts.pop(0)
            if parts and parts[-1] == "":
                parts.pop(-1)
            if parts:
                flush_list()
                flush_quote()
                in_table = True
                table_rows.append(parts)
                continue

        if in_table:
            flush_table()

        # Horizontal rule
        if re.match(r"^(\*|\-|_){3,}$", stripped):
            flush_list()
            flush_quote()
            out.append("<hr>")
            continue

        # Headers
        m_head = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m_head:
            flush_list()
            flush_quote()
            level = len(m_head.group(1))
            h_text = m_head.group(2).strip()
            # Explicit anchor syntax: ## Title {#anchor-id}
            m_explicit = re.search(r"\s*\{#([a-zA-Z0-9_-]+)\}\s*$", h_text)
            if m_explicit:
                explicit_id = m_explicit.group(1)
                h_text = h_text[:m_explicit.start()].strip()
                plain_text = re.sub(r"<[^>]+>", "", h_text)
                plain_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain_text)
                plain_text = re.sub(r"[`*_*]", "", plain_text)
                auto_id = slugify(plain_text)
                if auto_id and auto_id != explicit_id:
                    out.append(f'<h{level} id="{explicit_id}"><span id="{auto_id}"></span>{inline_markdown(h_text)}</h{level}>')
                else:
                    out.append(f'<h{level} id="{explicit_id}">{inline_markdown(h_text)}</h{level}>')
                continue

            # Remove any raw HTML tags or Markdown formatting for anchor slug
            plain_text = re.sub(r"<[^>]+>", "", h_text)
            plain_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain_text)
            plain_text = re.sub(r"[`*_*]", "", plain_text)
            h_id = slugify(plain_text)
            out.append(f'<h{level} id="{h_id}">{inline_markdown(h_text)}</h{level}>')
            continue

        # Blockquotes
        if stripped.startswith(">"):
            flush_list()
            in_blockquote = True
            quote_lines.append(re.sub(r"^>\s?", "", line))
            continue
        elif in_blockquote:
            flush_quote()

        # Unordered lists
        m_ul = re.match(r"^[\*\-\+]\s+(.*)$", stripped)
        if m_ul:
            if not in_list or list_type != "ul":
                flush_list()
                in_list = True
                list_type = "ul"
                out.append("<ul>")
            out.append(f"<li>{inline_markdown(m_ul.group(1))}</li>")
            continue

        # Ordered lists
        m_ol = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m_ol:
            if not in_list or list_type != "ol":
                flush_list()
                in_list = True
                list_type = "ol"
                out.append("<ol>")
            out.append(f"<li>{inline_markdown(m_ol.group(1))}</li>")
            continue

        if in_list and not stripped:
            flush_list()
            continue

        # Empty line
        if not stripped:
            flush_list()
            flush_quote()
            continue

        # Paragraph
        if not in_list and not in_blockquote and not in_table:
            out.append(f"<p>{inline_markdown(stripped)}</p>")

    flush_list()
    flush_quote()
    flush_table()

    return "\n".join(out)


def bundle_docs() -> None:
    """Read all documentation Markdown files and generate docs_data.py."""
    # Ensure infographic artifacts are freshly generated if generator exists
    gen_script = os.path.join(THIS_DIR, "generate_infographic_html.py")
    if os.path.isfile(gen_script):
        try:
            import subprocess
            subprocess.run([sys.executable, gen_script], check=True, cwd=PROJECT_ROOT)
        except Exception as e:
            print(f"  [!] Note: generate_infographic_html.py encountered notice: {e}")

    print("==> Bundling Documentation into groundzero/web/docs_data.py...")
    docs_payload: Dict[str, dict] = {}

    for doc in DOC_FILES:
        full_path = os.path.join(PROJECT_ROOT, doc["rel_path"])
        if not os.path.exists(full_path):
            print(f"  [!] WARNING: Documentation file missing: {doc['rel_path']}")
            continue

        with open(full_path, encoding="utf-8") as fh:
            raw_md = fh.read()

        html_body = markdown_to_html(raw_md)
        docs_payload[doc["id"]] = {
            "id": doc["id"],
            "title": doc["title"],
            "icon": doc["icon"],
            "rel_path": doc["rel_path"],
            "html": html_body,
        }
        print(f"  [✓] Bundled {doc['rel_path']} ({len(raw_md):,} chars md -> {len(html_body):,} chars html)")

    out_file = os.path.normpath(OUT_PATH)
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    json_dumps = json.dumps(docs_payload, indent=2, ensure_ascii=False)

    file_content = f'''"""
Auto-generated by tools/bundle_docs.py — do not edit manually.
Re-generated automatically during build or via: python tools/bundle_docs.py
"""

DOCS_DATA: dict = {json_dumps}
'''

    with open(out_file, "w", encoding="utf-8") as fh:
        fh.write(file_content)

    print(f"==> Successfully written -> {os.path.relpath(out_file)}")


if __name__ == "__main__":
    bundle_docs()
