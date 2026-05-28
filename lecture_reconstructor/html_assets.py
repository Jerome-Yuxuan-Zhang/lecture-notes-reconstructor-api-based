from __future__ import annotations


LECTURE_CSS = """
:root {
  color: #202124;
  background: #ffffff;
  font-family: "Palatino Linotype", "Book Antiqua", Palatino, "Noto Serif SC",
    "Source Han Serif SC", "Songti SC", serif;
}
body {
  margin: 0;
  line-height: 1.8;
  font-family: inherit;
}
main {
  max-width: 980px;
  margin: 0 auto;
  padding: 32px 42px 64px;
}
h1, h2, h3, h4, table, figcaption, .formula-card {
  font-family: inherit;
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
  tex: { inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] },
  svg: { fontCache: 'global' }
};
</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"></script>
"""


def ensure_full_html(content: str, title: str = "Lecture Notes") -> str:
    stripped = content.strip()
    if "<html" in stripped.lower() and "</html>" in stripped.lower():
        html = stripped
        if "MathJax" not in html:
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
