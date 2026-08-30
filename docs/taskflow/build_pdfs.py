"""Render the submission PDFs from their markdown sources.

`submission/README.md` said the PDFs were "markdown -> styled HTML -> headless Chrome"
and left the middle step to a human, which meant the rendered artefacts drifted from
their sources every time the sources changed -- exactly the failure the rest of this
repo engineers against. This makes the step reproducible.

    uv run --with markdown python docs/taskflow/build_pdfs.py

Sources are the authority. Never hand-edit a PDF; edit the markdown and re-run this.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

import markdown

ROOT = pathlib.Path(__file__).resolve().parents[2]

JOBS = [
    (ROOT / "README.md", ROOT / "submission" / "LedgerLens_README.pdf", "LedgerLens — README"),
    (ROOT / "docs" / "business_proposal.md", ROOT / "submission" / "LedgerLens_Business_Proposal.pdf",
     "LedgerLens — Business Proposal"),
]

# Print-first CSS. Deliberately plain: this is a document a judge reads on paper or in a
# viewer, not a web page, so the priorities are margins, table legibility and not
# splitting a table across a page break.
CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Charter","Georgia","Times New Roman",serif; font-size: 10.5pt;
       line-height: 1.5; color: #16181d; margin: 0; }
h1 { font-size: 21pt; line-height: 1.2; margin: 0 0 4pt; letter-spacing: -0.01em; }
h2 { font-size: 14pt; margin: 20pt 0 6pt; padding-bottom: 3pt;
     border-bottom: 1.2pt solid #5B21B6; color: #3b1a86; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 4pt; color: #22252b; break-after: avoid; }
h4 { font-size: 10.5pt; margin: 11pt 0 3pt; color: #3a3f47; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
blockquote { margin: 8pt 0; padding: 6pt 12pt; border-left: 2.5pt solid #5B21B6;
             background: #f7f5fd; break-inside: avoid; }
blockquote p { margin: 3pt 0; }
code { font-family: "DejaVu Sans Mono",Menlo,Consolas,monospace; font-size: 8.8pt;
       background: #f2f3f5; padding: 0.5pt 3pt; border-radius: 2pt; }
pre { background: #f7f8fa; border: 0.6pt solid #dfe2e7; border-radius: 3pt;
      padding: 7pt 9pt; overflow-x: auto; break-inside: avoid; font-size: 8.5pt; }
pre code { background: none; padding: 0; font-size: 8.5pt; }
table { border-collapse: collapse; width: 100%; margin: 9pt 0; font-size: 9pt;
        break-inside: avoid; }
th { background: #f0eefb; text-align: left; font-weight: 600; color: #2f2a52; }
th, td { border: 0.6pt solid #d8dce2; padding: 4pt 6pt; vertical-align: top; }
tr:nth-child(even) td { background: #fbfbfc; }
hr { border: none; border-top: 0.6pt solid #d8dce2; margin: 16pt 0; }
a { color: #4c1d95; text-decoration: none; }
strong { color: #0d0f13; }
img { max-width: 100%; }
"""

HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title><style>{css}</style></head><body>{body}</body></html>"""


def chrome() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("no Chrome/Chromium on PATH -- needed for --print-to-pdf")


def build(src: pathlib.Path, out: pathlib.Path, title: str, browser: str) -> None:
    body = markdown.markdown(
        src.read_text(),
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )
    with tempfile.TemporaryDirectory() as tmp:
        page = pathlib.Path(tmp) / "page.html"
        page.write_text(HTML.format(title=title, css=CSS, body=body))
        subprocess.run(
            [browser, "--headless", "--disable-gpu", "--no-sandbox",
             f"--print-to-pdf={out}", "--no-pdf-header-footer",
             "--virtual-time-budget=6000", page.as_uri()],
            check=True, capture_output=True,
        )
    kb = out.stat().st_size / 1024
    print(f"  {src.relative_to(ROOT)} -> {out.relative_to(ROOT)}  ({kb:,.0f} KB)")


def main() -> None:
    browser = chrome()
    print(f"rendering with {browser}\n")
    for src, out, title in JOBS:
        build(src, out, title, browser)
    print("\nDone. The markdown is the authority -- never hand-edit these.")


if __name__ == "__main__":
    main()
