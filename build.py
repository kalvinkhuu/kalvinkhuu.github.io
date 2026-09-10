#!/usr/bin/env python3
"""
build.py — render cv.yaml into a portfolio website and a LaTeX CV.

    python build.py                # generate site/ and build/resume.tex
    python build.py --pdf          # also run pdflatex and copy the PDF into site/
    python build.py --watch        # rebuild whenever cv.yaml or a template changes

Outputs
    build/resume.tex     LaTeX source (intermediate, kept for debugging)
    site/index.html      the portfolio website
    site/<pdf_filename>  the compiled CV, if --pdf was passed
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

ROOT = Path(__file__).parent
TEMPLATES = ROOT / "templates"
ASSETS = ROOT / "assets"
BUILD = ROOT / "build"
SITE = ROOT / "site"


# ---------------------------------------------------------------------------
# Inline markup: **bold**, _italic_, [label](url)
# ---------------------------------------------------------------------------

MARKUP = re.compile(
    r"\*\*(?P<bold>.+?)\*\*"
    r"|(?<![\w\\])_(?P<italic>[^_]+?)_(?!\w)"
    r"|\[(?P<label>[^\]]+)\]\((?P<url>[^)\s]+)\)"
)

LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    """Escape the ten characters LaTeX treats specially.

    A tilde directly before a digit is treated as "approximately" and set as
    $\\sim$; everywhere else it stays a literal tilde.
    """
    escaped = "".join(LATEX_ESCAPES.get(c, c) for c in str(text))
    return re.sub(r"\\textasciitilde\{\}(?=\d)", r"$\\sim$", escaped)


def latex_escape_url(url: str) -> str:
    """Escape only what actually breaks inside \\href{...}."""
    return url.replace("\\", r"\\").replace("%", r"\%").replace("#", r"\#").replace("&", r"\&")


def html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_markup(text, fmt: str):
    """Convert the shared inline markup into LaTeX or HTML."""
    if text is None:
        return ""
    text = " ".join(str(text).split())  # collapse YAML line folding

    esc = latex_escape if fmt == "latex" else html_escape
    out, pos = [], 0

    for m in MARKUP.finditer(text):
        out.append(esc(text[pos : m.start()]))
        if m.group("bold"):
            inner = render_markup(m.group("bold"), fmt)
            out.append(rf"\textbf{{{inner}}}" if fmt == "latex" else f"<strong>{inner}</strong>")
        elif m.group("italic"):
            inner = render_markup(m.group("italic"), fmt)
            out.append(rf"\emph{{{inner}}}" if fmt == "latex" else f"<em>{inner}</em>")
        else:
            label, url = render_markup(m.group("label"), fmt), m.group("url")
            if fmt == "latex":
                out.append(rf"\href{{{latex_escape_url(url)}}}{{\underline{{{label}}}}}")
            else:
                out.append(f'<a href="{html_escape(url)}" target="_blank" rel="noopener">{label}</a>')
        pos = m.end()

    out.append(esc(text[pos:]))
    result = "".join(out)
    return result if fmt == "latex" else Markup(result)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def visible(items, target: str):
    """Drop entries disabled outright or not meant for this target."""
    kept = []
    for item in items or []:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        if item.get("enabled") is False:
            continue
        if target not in item.get("targets", ["pdf", "web"]):
            continue
        kept.append(item)
    return kept


def daterange(entry: dict, dash: str) -> str:
    start, end = entry.get("start"), entry.get("end")
    if start and end:
        return f"{start} {dash} {end}"
    return str(start or end or "")


def format_langs(languages) -> str:
    return ", ".join(f"{l['name']} ({l['level']})" for l in languages or [])


def normalise_highlights(items):
    """Allow a highlight to be a bare string or {text:, items: []}."""
    out = []
    for item in items or []:
        if isinstance(item, dict):
            if item.get("enabled") is False:
                continue
            out.append({"text": item.get("text", ""), "items": item.get("items") or []})
        else:
            out.append({"text": item, "items": []})
    return out


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------

def latex_env() -> Environment:
    """Jinja with delimiters that do not collide with LaTeX syntax."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((#",
        comment_end_string="#))",
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )
    env.filters["rt"] = lambda t: render_markup(t, "latex")
    env.filters["esc"] = latex_escape
    env.filters["url"] = latex_escape_url
    env.filters["visible"] = lambda i: visible(i, "pdf")
    env.filters["dates"] = lambda e: daterange(e, "--")
    env.filters["highlights"] = normalise_highlights
    env.filters["langs"] = format_langs
    return env


def html_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    env.filters["rt"] = lambda t: render_markup(t, "html")
    env.filters["visible"] = lambda i: visible(i, "web")
    env.filters["dates"] = lambda e: daterange(e, "–")
    env.filters["highlights"] = normalise_highlights
    env.filters["langs"] = format_langs
    return env


# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------

def load_cv() -> dict:
    with open(ROOT / "cv.yaml", encoding="utf-8") as fh:
        cv = yaml.safe_load(fh)

    for section in ("education", "skills", "publications", "experience", "projects"):
        cv.setdefault(section, [])
    cv.setdefault("about", [])
    cv.setdefault("research_interests", [])
    cv.setdefault("summary", {"enabled": False, "text": ""})
    return cv


def build_tex(cv: dict) -> Path:
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "resume.tex"
    out.write_text(latex_env().get_template("resume.tex.j2").render(**cv), encoding="utf-8")
    print(f"  tex   {out.relative_to(ROOT)}")
    return out


def build_site(cv: dict) -> Path:
    SITE.mkdir(exist_ok=True)
    out = SITE / "index.html"
    ctx = {**cv, "year": datetime.now().year}
    out.write_text(html_env().get_template("index.html.j2").render(**ctx), encoding="utf-8")

    for asset in ASSETS.glob("*"):
        if asset.is_file():
            shutil.copy2(asset, SITE / asset.name)

    print(f"  html  {out.relative_to(ROOT)}")
    return out


def build_pdf(cv: dict, tex: Path) -> Path | None:
    if not shutil.which("pdflatex"):
        print("  pdf   skipped — pdflatex not found on PATH")
        return None

    for _ in range(2):  # twice, so page refs settle
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
            cwd=tex.parent,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        print("  pdf   FAILED — last 40 lines of pdflatex output:\n")
        print("\n".join(result.stdout.splitlines()[-40:]))
        raise SystemExit(1)

    SITE.mkdir(exist_ok=True)
    dest = SITE / cv["meta"].get("pdf_filename", "cv.pdf")
    shutil.copy2(tex.with_suffix(".pdf"), dest)
    print(f"  pdf   {dest.relative_to(ROOT)}")
    return dest


def build(pdf: bool) -> None:
    print("building…")
    cv = load_cv()
    tex = build_tex(cv)
    build_site(cv)
    if pdf:
        build_pdf(cv, tex)
    print("done.\n")


def watch(pdf: bool) -> None:
    watched = [ROOT / "cv.yaml", *TEMPLATES.glob("*.j2")]
    stamps = {}
    print("watching cv.yaml and templates/ — Ctrl-C to stop\n")
    while True:
        current = {p: p.stat().st_mtime for p in watched if p.exists()}
        if current != stamps:
            stamps = current
            try:
                build(pdf)
            except SystemExit:
                pass
            except Exception as exc:  # keep watching through template errors
                print(f"  error: {exc}\n")
        time.sleep(0.5)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", action="store_true", help="compile the LaTeX CV with pdflatex")
    ap.add_argument("--watch", action="store_true", help="rebuild on file change")
    args = ap.parse_args()

    if args.watch:
        try:
            watch(args.pdf)
        except KeyboardInterrupt:
            sys.exit(0)
    else:
        build(args.pdf)


if __name__ == "__main__":
    main()
