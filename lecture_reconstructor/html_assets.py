from __future__ import annotations

import re


LECTURE_CSS = """
:root {
  color: #202124;
  background: #ffffff;
  font-family: "Palatino Linotype", "Book Antiqua", Palatino, "Noto Serif SC",
    "Source Han Serif SC", "Songti SC", serif;
}
body {
  margin: 0;
  font-size: 12pt;
  line-height: 1.8;
  font-family: inherit;
}
main {
  max-width: 980px;
  margin: 0 auto;
  padding: 2.54cm;
}
h1, h2, h3, h4, table, figcaption, .formula-card {
  font-family: inherit;
}
h1 {
  font-size: 12pt;
  font-weight: 700;
  border-bottom: 1px solid #999999;
  padding-bottom: 8pt;
  margin-top: 24pt;
}
h2, h3, h4 {
  font-size: 12pt;
  font-weight: 700;
}
hr.chapter-separator {
  border: 0;
  border-top: 1px solid #999999;
  margin: 24pt 0;
}
.highlight, mark {
  background: #fff3b0;
  color: inherit;
  padding: 0 2px;
}
strong, b {
  color: inherit;
}
p {
  margin-top: 10pt;
  margin-bottom: 10pt;
  text-indent: 2em;
}
li {
  margin-top: 4pt;
  margin-bottom: 2pt;
}
li p {
  text-indent: 0;
}
.formula-card, .definition-card, .example-card, .warning-card, .compare-card {
  border: 1px solid #d8d8d8;
  border-radius: 4px;
  padding: 12px 18px;
  margin: 14px 0;
  background: transparent;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.formula-card {
  border-color: #ead8d6;
  border-left: 4px solid #c0392b;
}
.definition-card {
  border-left: 4px solid #2c5aa0;
}
.example-card {
  border-left: 4px solid #2e7d5b;
}
.warning-card, .compare-card {
  border-left: 4px solid #c77a1c;
}
.mm-badge {
  display: inline-block;
  color: #c0392b;
  font-weight: bold;
  font-size: 0.92em;
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}
figure {
  margin: 18px 0;
}
img {
  display: block;
  width: 70%;
  max-width: 100%;
  height: auto;
  margin: 0 auto;
}
img.wide, figure.wide img {
  width: 100%;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}
th, td {
  border: 1px solid #d8d8d8;
  padding: 7px 9px;
  vertical-align: top;
}
@page {
  margin: 2.54cm;
}
@media print {
  main {
    max-width: none;
    padding: 0;
  }
  a {
    color: inherit;
    text-decoration: none;
  }
}
"""


MATHJAX_SCRIPT = """
<script>
window.MathJax = {
  loader: { load: ['[tex]/unicode'] },
  tex: {
    packages: { '[+]': ['unicode'] },
    inlineMath: [['\\\\(', '\\\\)']],
    displayMath: [['\\\\[', '\\\\]']],
    processEscapes: true,
    macros: {
      pounds: ['\\\\unicode{x00A3}', 0],
      euro: ['\\\\unicode{x20AC}', 0],
      rupee: ['\\\\unicode{x20B9}', 0],
      won: ['\\\\unicode{x20A9}', 0],
      ruble: ['\\\\unicode{x20BD}', 0],
      bitcoin: ['\\\\unicode{x20BF}', 0]
    }
  },
  chtml: { scale: 1 },
  options: { renderActions: { addMenu: [] } }
};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
"""


def _strip_mathjax_scripts(html: str) -> str:
    html = re.sub(
        r"<script\b(?=[^>]*\bsrc=[\"'][^\"']*mathjax[^\"']*[\"'])[^>]*>\s*</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html = re.sub(
        r"<script\b[^>]*>\s*(?:window\.)?MathJax\s*=\s*\{.*?\};?\s*</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return html


def ensure_full_html(content: str, title: str = "Lecture Notes") -> str:
    stripped = content.strip()
    if "<html" in stripped.lower() and "</html>" in stripped.lower():
        html = _strip_mathjax_scripts(stripped)
        html = html.replace("</head>", f"{MATHJAX_SCRIPT}\n</head>")
        if ".formula-card" not in html:
            html = html.replace("</head>", f"<style>{LECTURE_CSS}</style>\n</head>")
        return html

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{LECTURE_CSS}</style>
  {MATHJAX_SCRIPT}
</head>
<body>
<main>
{content}
</main>
</body>
</html>
"""
