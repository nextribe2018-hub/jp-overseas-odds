#!/usr/bin/env python3
"""data/latest.json を読み込み、単一ファイルの閲覧サイト site/index.html を生成する。"""
import json, os
ROOT = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = tpl.replace("__DATA__", payload).replace("__GENERATED__", data["generated_at_jst"])
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
out = os.path.join(ROOT, "docs", "index.html")
open(out, "w", encoding="utf-8").write(html)
print(f"wrote {out} ({len(html)//1024} KB) — {len(data['events'])} events / {len(data['games'])} games")
