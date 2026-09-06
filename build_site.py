#!/usr/bin/env python3
"""data/latest.json を読み込み、単一ファイルの閲覧サイト site/index.html を生成する。"""
import json, os
ROOT = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
fb_path = os.path.join(ROOT, "config", "firebase.json")
fb = ""
if os.path.exists(fb_path):
    try:
        cfg = json.load(open(fb_path, encoding="utf-8"))
        if cfg.get("projectId"):
            fb = ('<script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js"></script>\n'
                  '<script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-firestore-compat.js"></script>\n'
                  '<script>window.FIREBASE_CONFIG=' + json.dumps(cfg) + ';</script>')
            print("firebase: 掲示板を Firestore に接続 (project:", cfg["projectId"] + ")")
    except Exception as e:
        print("firebase.json を読めません:", e)
html = tpl.replace("__DATA__", payload).replace("__GENERATED__", data["generated_at_jst"]).replace("__FIREBASE__", fb)
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
out = os.path.join(ROOT, "docs", "index.html")
open(out, "w", encoding="utf-8").write(html)
print(f"wrote {out} ({len(html)//1024} KB) — {len(data['events'])} events / {len(data['games'])} games")
