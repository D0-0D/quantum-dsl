#!/usr/bin/env python3
"""report.md → report.html → report.pdf。

公式 $…$ / $$…$$ 由 node + 本地 KaTeX 预渲染成 HTML (不依赖浏览器里跑 JS), fig/*.svg 内联进页面 (才能用页面字体),
Chrome headless 打印成 A4 PDF。report.md 本身在 GitHub 上也能直接读 (公式、表、图都渲染)。
跑法: python3 build.py    (产物 report.html / report.pdf 不入库)
依赖: markdown-it-py、node、KaTeX 发行包 (解压到本目录 katex/ 或设 KATEX_DIR)、Chrome/Chromium (默认 playwright 的, 或设 CHROME)、
      宋体 / 黑体 / 楷体 / Times / Consolas 字体文件 (默认 WSL 下的 /mnt/c/Windows/Fonts, 或设 FONT_DIR)。
"""
import json
import os
import re
import subprocess
from pathlib import Path

from markdown_it import MarkdownIt

HERE = Path(__file__).resolve().parent
KATEX = Path(os.environ.get("KATEX_DIR", HERE / "katex"))
CHROME = Path(os.environ.get("CHROME", Path.home() / ".cache/ms-playwright/chromium-1223/chrome-linux64/chrome"))
FONTS = Path(os.environ.get("FONT_DIR", "/mnt/c/Windows/Fonts")).as_uri()
for need in (KATEX / "katex.min.js", CHROME):
    if not need.exists():
        raise SystemExit(f"缺 {need} (见文件头的依赖说明)")

src = (HERE / "report.md").read_text(encoding="utf-8")

# 1. 公式抽成占位符; 代码块与行内代码原样跳过 (split 的奇数段是代码)
maths: list[tuple[str, bool]] = []


def _stash(m: re.Match) -> str:
    maths.append((m.group(1) or m.group(2), m.group(1) is not None))
    return f"@@M{len(maths) - 1}@@"


MATH = re.compile(r"\$\$(.+?)\$\$|\$([^$\n]+?)\$", re.S)
parts = re.split(r"(```.*?```|`[^`\n]*`)", src, flags=re.S)
src = "".join(p if i % 2 else MATH.sub(_stash, p) for i, p in enumerate(parts))

# 2. Markdown → HTML; <img src="fig/x.svg"> 换成 SVG 正文
body = MarkdownIt("commonmark", {"html": True}).enable("table").render(src)
body = re.sub(r'<img src="(fig/[^"]+\.svg)"[^>]*>', lambda m: (HERE / m.group(1)).read_text(encoding="utf-8"), body)

# 3. KaTeX 预渲染 (公式写错直接报错, 不静默)
JS = (
    "const k=require(process.argv[1]);const m=JSON.parse(require('fs').readFileSync(0,'utf8'));"
    "process.stdout.write(JSON.stringify(m.map(([t,d])=>k.renderToString(t,{displayMode:d,throwOnError:true}))))"
)
rendered = json.loads(
    subprocess.run(
        ["node", "-e", JS, str(KATEX / "katex.min.js")],
        input=json.dumps(maths), capture_output=True, text=True, check=True,
    ).stdout
)
body = re.sub(r"@@M(\d+)@@", lambda m: rendered[int(m.group(1))], body)
assert "@@M" not in body and "$" not in re.sub(r"<pre>.*?</pre>|<code>.*?</code>", "", body, flags=re.S), "有没渲染的公式"

CSS = f"""
@font-face{{font-family:RSong;src:url("{FONTS}/simsun.ttc")}}
@font-face{{font-family:RHei;font-weight:100 900;src:url("{FONTS}/simhei.ttf")}}
@font-face{{font-family:RKai;src:url("{FONTS}/simkai.ttf")}}
@font-face{{font-family:RTimes;src:url("{FONTS}/times.ttf")}}
@font-face{{font-family:RTimes;font-weight:bold;src:url("{FONTS}/timesbd.ttf")}}
@font-face{{font-family:RTimes;font-style:italic;src:url("{FONTS}/timesi.ttf")}}
@font-face{{font-family:RMono;src:url("{FONTS}/consola.ttf")}}
@page{{size:A4;margin:22mm 20mm 20mm 20mm;@bottom-center{{content:counter(page);font-family:RTimes;font-size:9pt;color:#444}}}}
html{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
body{{font-family:RTimes,RSong,serif;font-size:10.5pt;line-height:1.62;color:#111;margin:0;text-align:justify}}
h1{{font-family:RTimes,RHei;font-size:22pt;text-align:center;margin:22mm 0 2mm;font-weight:normal;letter-spacing:1px}}
.sub{{font-family:RTimes,RHei;font-size:15pt;text-align:center;margin:0 0 10mm}}
h2{{font-family:RTimes,RHei;font-size:15pt;font-weight:normal;margin:7mm 0 3mm;padding-bottom:1.2mm;border-bottom:1.2pt solid #1f3f7a;break-after:avoid}}
h3{{font-family:RTimes,RHei;font-size:12pt;font-weight:normal;margin:6mm 0 2mm;break-after:avoid}}
h4{{font-family:RTimes,RHei;font-size:10.5pt;font-weight:normal;margin:4mm 0 1mm;break-after:avoid}}
p{{margin:0 0 2.2mm;text-indent:2em;orphans:2;widows:2}}
li p,td p,th p,blockquote p,figure p,.noindent{{text-indent:0}}
strong{{font-family:RTimes,RHei;font-weight:bold}}
ul,ol{{margin:0 0 2.2mm;padding-left:2.4em}}li{{margin:0.4mm 0}}
table{{border-collapse:collapse;width:100%;font-size:9pt;line-height:1.5;margin:2mm 0 4mm;border-top:1.2pt solid #111;border-bottom:1.2pt solid #111;text-align:left}}
th{{font-family:RTimes,RHei;font-weight:normal;border-bottom:0.6pt solid #111;padding:1.4mm 1.6mm;vertical-align:bottom;background:#f2f5fb}}
td{{padding:1.2mm 1.6mm;vertical-align:top;border-bottom:0.3pt solid #c9ced8}}
tr{{break-inside:avoid}}td:first-child,th:first-child{{white-space:nowrap}}.front td{{white-space:normal}}
code{{font-family:RMono,RSong,monospace;font-size:0.88em;background:#f3f4f7;padding:0 2px;border-radius:2px}}
pre{{background:#f6f7f9;border:0.4pt solid #d5d9e0;border-radius:2px;padding:2mm 3mm;margin:2mm 0 3.5mm;line-height:1.38;break-inside:avoid;white-space:pre-wrap;text-align:left}}
pre code{{background:none;padding:0;font-size:8.2pt}}
figure{{margin:3mm 0 4mm;text-align:center;break-inside:avoid}}
figure img,figure svg{{max-width:100%}}
figcaption,.cap{{font-family:RTimes,RKai;font-size:9pt;line-height:1.5;margin-top:1.5mm;text-align:center;text-indent:0}}
.cap{{margin:4mm 0 0;break-after:avoid}}
.front{{width:78%;margin:0 auto 8mm;font-size:10.5pt;border:none}}
.front td{{border:none;padding:1.6mm 2mm}}.front td:first-child{{font-family:RHei;width:6em;text-align:right}}
.abstract{{border-left:2.4pt solid #1f3f7a;background:#f4f6fb;padding:3mm 4mm;margin:0 0 4mm}}.abstract p{{text-indent:2em;margin:0 0 1.5mm}}
.todo{{color:#b3261e}}
.katex{{font-size:1.02em}}.katex-display{{margin:2.2mm 0 3mm}}
.refs p{{text-indent:-2em;padding-left:2em;margin:0 0 0.6mm;font-size:8.5pt;line-height:1.42;text-align:left}}
.pb{{break-before:page}}
"""

html = (
    '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
    "<title>超导量子处理器设计自动化 · SRT 结题报告</title>"
    f'<link rel="stylesheet" href="{KATEX.as_uri()}/katex.min.css"><style>{CSS}</style></head><body>{body}</body></html>'
)
(HERE / "report.html").write_text(html, encoding="utf-8")

subprocess.run(
    [str(CHROME), "--headless", "--no-sandbox", "--allow-file-access-from-files", "--no-pdf-header-footer",
     "--virtual-time-budget=15000", f"--print-to-pdf={HERE / 'report.pdf'}", (HERE / "report.html").as_uri()],
    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180,
)
print(f"{len(maths)} 个公式 → {HERE / 'report.pdf'}")
