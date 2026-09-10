# CV pipeline

One YAML file drives both a portfolio website and a LaTeX PDF.

```
cv.yaml ──▶ build.py ──┬──▶ templates/resume.tex.j2 ──▶ build/resume.tex ──pdflatex──▶ site/Kalvin_Khuu_CV.pdf
                       └──▶ templates/index.html.j2 ──▶ site/index.html
```

Edit `cv.yaml`, push, and GitHub Actions rebuilds the PDF and redeploys the site.

## Local use

```bash
pip install -r requirements.txt

python build.py            # website + resume.tex
python build.py --pdf      # also compile the PDF (needs pdflatex)
python build.py --watch    # rebuild on every save
```

Open `site/index.html` in a browser, or `python -m http.server -d site 8000`.

## Layout

| Path | Purpose |
| --- | --- |
| `cv.yaml` | The only file you normally edit. |
| `build.py` | Renderer: markup conversion, filters, pdflatex invocation. |
| `templates/resume.tex.j2` | LaTeX template. Your original preamble, unchanged. |
| `templates/index.html.j2` | Website template. Your original CSS, unchanged. |
| `assets/` | Files copied verbatim into `site/` (photo, favicon, …). |
| `build/` | LaTeX intermediates. |
| `site/` | What gets deployed. |

## Writing cv.yaml

**Inline markup** works in any text field and is translated per output:

| You write | PDF | Website |
| --- | --- | --- |
| `**text**` | `\textbf{text}` | `<strong>` |
| `_text_` | `\emph{text}` | `<em>` |
| `[label](https://url)` | `\href{...}{\underline{label}}` | `<a href>` |

Special characters are escaped for you. Write `C#`, `100%`, `R&D` and `~22%`
directly — no backslashes needed. A tilde before a digit becomes `$\sim$` in the
PDF.

**Showing and hiding entries.** Your old `.tex` had a lot of commented-out
blocks. Instead of deleting or commenting, tag the entry:

```yaml
- role: Chief Lifeguard
  enabled: false          # hidden everywhere, still on record

- role: Research Assistant III
  targets: [pdf]          # PDF only (default is [pdf, web])
```

**Nested bullets.** A highlight is either a string or an object with sub-items:

```yaml
highlights:
  - A flat bullet
  - text: A parent bullet
    items:
      - "**Research:** a sub-bullet"
      - "**Validation:** another sub-bullet"
```

**Section order** is set per output under `layout`, so the PDF can lead with
Education while the site leads with About:

```yaml
layout:
  pdf:
    order: [education, skills, publications, experience, projects]
  web:
    order: [about, publications, education, experience, skills, projects]
```

Renaming a section is a matter of editing `layout.*.titles`.

## Deployment

`.github/workflows/deploy.yml` runs on every push that touches `cv.yaml`,
`build.py`, `templates/` or `assets/`. It renders the templates, compiles the
PDF in a TeX Live container, and publishes `site/` to GitHub Pages.

One-time setup: **Settings → Pages → Source → GitHub Actions**.

The compiled PDF is also attached to each workflow run as an artifact, so a
failed Pages deploy still leaves you a downloadable CV.

If you would rather commit `site/` and serve it from a branch, drop the `site/`
line from `.gitignore` and run `python build.py --pdf` before committing.

## Adding a section

1. Add the data to `cv.yaml`.
2. Add a `section_<name>()` macro to whichever templates should show it.
3. Register it in `layout.pdf.order` / `layout.web.order` and in `titles`.

In `index.html.j2` the macro also needs an entry in the `renderers` map near the
bottom of the template; in `resume.tex.j2` it needs a branch in the dispatch
`if` at the end of the file.

## Notes

- Jinja uses non-standard delimiters in the LaTeX template (`((* *))`, `((( )))`,
  `((# #))`) so that `{}`, `%` and `#` stay available to TeX. The HTML template
  uses ordinary `{{ }}` and `{% %}`.
- `build.py` uses `StrictUndefined`, so a typo'd field fails the build loudly
  rather than rendering an empty string.
