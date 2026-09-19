#!/usr/bin/env python3
"""data/latest.json を読み込み、単一ファイルの閲覧サイト site/index.html を生成する。"""
import json, os
ROOT = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
ai_path = os.path.join(ROOT, "data", "ai_comments.json")
try:
    ai = json.load(open(ai_path, encoding="utf-8")).get("comments", {})
    data["ai"] = {k: {"text": v["text"], "ts": v["ts"], "kind": v["kind"], "hash": v["hash"], "auto_posted": v.get("auto_posted")} for k, v in ai.items()}
except Exception:
    data["ai"] = {}
def payload_of(d): return json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
payload = None
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
# ---- 国コードの補完（watchlist から）
wl = json.load(open(os.path.join(ROOT, "config", "watchlist.json"), encoding="utf-8"))
cmap = {f"{i['source']}:{i['id']}": i.get("country") for i in wl["items"]}
data["countries"] = wl.get("countries", {})
for e in data["events"] + data.get("archive", []):
    e["country"] = e.get("country") or cmap.get(e["key"]) or ("JP" if e.get("scope", "japan") == "japan" else "WORLD")
# ---- 特設ページ
try: features = json.load(open(os.path.join(ROOT, "config", "features.json"), encoding="utf-8"))
except Exception: features = []
try: news_log = json.load(open(os.path.join(ROOT, "data", "news_log.json"), encoding="utf-8"))
except Exception: news_log = {}
try: fbriefs = json.load(open(ai_path, encoding="utf-8")).get("features", {})
except Exception: fbriefs = {}
allev = {e["key"]: e for e in data["events"] + data.get("archive", [])}
data["features"] = []
for ft in features:
    evs = [allev[k] for k in ft["events"] if k in allev]
    live = [e for e in evs if e.get("status") != "resolved"]
    top = None
    for k, kw in ft.get("headline", [])[:1]:
        ev = allev.get(k)
        if ev:
            o = next((o for o in ev["outcomes"] if kw.lower() in ((o.get("name_ja") or "") + " " + (o.get("name") or "")).lower()), None)
            if o: top = {"ev": ev["title_ja"], "name": o.get("name_ja") or o["name"], "prob": o["prob"], "prob_24h": o.get("prob_24h")}
    data["features"].append({"slug": ft["slug"], "title_ja": ft["title_ja"], "title_en": ft["title_en"], "cat": ft["cat"], "lead": ft["lead"], "n": len(live), "top": top, "news_n": len(news_log.get("feature:" + ft["slug"], []))})
html = tpl.replace("__DATA__", payload_of(data)).replace("__GENERATED__", data["generated_at_jst"]).replace("__FIREBASE__", fb).replace("__BASE__", "./")
os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
out = os.path.join(ROOT, "docs", "index.html")
open(out, "w", encoding="utf-8").write(html)
print(f"wrote {out} ({len(html)//1024} KB) — {len(data['events'])} events / {len(data['games'])} games")
for ft in features:
    keys = set(ft["events"])
    fd = dict(data)
    fd["events"] = [e for e in data["events"] if e["key"] in keys]
    fd["archive"] = [e for e in data.get("archive", []) if e["key"] in keys]
    fd["games"] = [g for g in data["games"] if g.get("league_ja") in set(ft.get("games", []))]
    fd["ai"] = {k: v for k, v in data.get("ai", {}).items() if k in keys}
    fd["feature"] = {"slug": ft["slug"], "title_ja": ft["title_ja"], "title_en": ft["title_en"], "cat": ft["cat"], "lead": ft["lead"],
                     "headline": ft.get("headline", []), "calendar": ft.get("calendar", []), "news_q": ft.get("news_q", []),
                     "news": sorted(news_log.get("feature:" + ft["slug"], []), key=lambda n: -n["ts"])[:40],
                     "brief": fbriefs.get(ft["slug"])}
    fd["features"] = data["features"]
    fhtml = tpl.replace("__DATA__", payload_of(fd)).replace("__GENERATED__", data["generated_at_jst"]).replace("__FIREBASE__", fb).replace("__BASE__", "../../")
    fdir = os.path.join(ROOT, "docs", "f", ft["slug"]); os.makedirs(fdir, exist_ok=True)
    open(os.path.join(fdir, "index.html"), "w", encoding="utf-8").write(fhtml)
    print(f"  feature {ft['slug']}: {len(fd['events'])} events, {len(fd['feature']['news'])} news, brief={'yes' if fd['feature']['brief'] else 'no'} ({len(fhtml)//1024} KB)")
