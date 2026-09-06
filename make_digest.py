#!/usr/bin/env python3
"""data/latest.json から毎日のメール本文（HTML）と件名を生成する。
出力: digest/email.html, digest/subject.txt"""
import json, os, html
from datetime import datetime, timezone, timedelta
ROOT = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
SITE = os.environ.get("SITE_URL", "").strip()
JST = timezone(timedelta(hours=9))
NOW = D["generated_at"]; today = datetime.fromtimestamp(NOW, JST)
CATS = D["categories"]; SRC = {"polymarket": "Polymarket", "kalshi": "Kalshi", "manifold": "Manifold"}
e = html.escape
def pct(p): return "—" if p is None else f"{p*100:.1f}%"
def odds(p): return "—" if not p else f"{min(999, 1/p):.2f}倍"
def fmt_d(ts): return datetime.fromtimestamp(ts, JST).strftime("%-m/%-d") if ts else ""
def usd(v):
    if v is None: return "—"
    return f"${v/1e6:.2f}M" if v >= 1e6 else f"${v/1e3:.0f}K" if v >= 1e3 else f"${v:.0f}"
def delta(a, b):
    if a is None or b is None: return '<span style="color:#888">—</span>'
    d = (a - b) * 100
    if abs(d) < 0.05: return '<span style="color:#888">±0.0pt</span>'
    col = "#c8302a" if d > 0 else "#1d7a4f"
    return f'<span style="color:{col};font-weight:600">{d:+.1f}pt</span>'
def oname(o, ev=None):
    if o.get("name_ja"): return o["name_ja"]
    if ev is not None and len(ev["outcomes"]) == 1 and o["name"] and len(o["name"]) > 24: return "はい（YES）"
    return o["name"]

# 注目の動き
rows = [(ev, o) for ev in D["events"] if ev.get("scope") != "global" for o in ev["outcomes"] if o["prob"] is not None]
mv24 = sorted([r for r in rows if r[1].get("prob_24h") is not None], key=lambda r: -abs(r[1]["prob"] - r[1]["prob_24h"]))[:8]
mv7 = sorted([r for r in rows if r[1].get("prob_7d") is not None], key=lambda r: -abs(r[1]["prob"] - r[1]["prob_7d"]))[:8]

TD = 'style="padding:6px 8px;border-bottom:1px solid #e6e7ec;font-size:13px;vertical-align:top"'
TDR = 'style="padding:6px 8px;border-bottom:1px solid #e6e7ec;font-size:13px;text-align:right;white-space:nowrap;font-family:Menlo,Consolas,monospace"'
TH = 'style="padding:6px 8px;border-bottom:2px solid #1a1c25;font-size:11px;color:#666;text-align:left;letter-spacing:.06em"'
THR = TH.replace("text-align:left", "text-align:right")

def mover_table(items, key):
    out = [f'<table cellspacing="0" cellpadding="0" width="100%"><tr><th {TH}>選択肢 / マーケット</th><th {THR}>確率</th><th {THR}>変化</th></tr>']
    for ev, o in items:
        out.append(f'<tr><td {TD}><b>{e(oname(o, ev))}</b><br><span style="color:#777;font-size:12px">{e(ev["title_ja"])}（{SRC[ev["source"]]}）</span></td><td {TDR}><b>{pct(o["prob"])}</b></td><td {TDR}>{delta(o["prob"], o.get(key))}</td></tr>')
    return "".join(out) + "</table>"

def cat_table(evs):
    out = [f'<table cellspacing="0" cellpadding="0" width="100%"><tr><th {TH}>マーケット</th><th {TH}>首位の選択肢</th><th {THR}>確率</th><th {THR}>倍率</th><th {THR}>24h</th><th {THR}>7日</th><th {THR}>出来高</th></tr>']
    for ev in evs:
        outs = sorted(ev["outcomes"], key=lambda o: -(o["prob"] or 0))
        top = outs[0]
        second = ""
        if len(outs) > 1 and outs[1]["prob"] is not None and (ev.get("sum_to_one", True)):
            second = f'<br><span style="color:#777;font-size:12px">2位 {e(oname(outs[1], ev))} {pct(outs[1]["prob"])}（{odds(outs[1]["prob"])}）</span>'
        vol = f'M{ev["volume"]:,}' if ev["source"] == "manifold" else usd(ev["volume"])
        link = (f' <a href="{e(ev["url"])}" style="color:#2b3f7a;font-size:11px">賭けを見る↗</a>'
                f' <a href="{e(ev.get("url_ja") or ev["url"])}" style="color:#2b3f7a;font-size:11px">日本語訳</a>')
        news = "".join(f'<br><span style="font-size:11px;color:#555">▸ <a href="{e(n["link"])}" style="color:#555">{e(n["title"][:48])}</a> <span style="color:#999">{e(n.get("source") or "")} {fmt_d(n.get("ts"))}</span></span>' for n in (ev.get("news") or [])[:2])
        others = ""
        if len(outs) > 2 and ev.get("sum_to_one", True):
            others = '<br><span style="color:#777;font-size:11px">' + " ／ ".join(f'{e(oname(o, ev))} {pct(o["prob"])}（{odds(o["prob"])}）' for o in outs[2:5] if o["prob"] is not None) + "</span>"
        out.append(f'<tr><td {TD}>{e(ev["title_ja"])}<br><span style="color:#999;font-size:11px">{SRC[ev["source"]]}</span>{link}{news}</td><td {TD}>{e(oname(top, ev))}{second}{others}</td><td {TDR}><b>{pct(top["prob"])}</b></td><td {TDR}>{odds(top["prob"])}</td><td {TDR}>{delta(top["prob"], top.get("prob_24h"))}</td><td {TDR}>{delta(top["prob"], top.get("prob_7d"))}</td><td {TDR} style="color:#888">{vol}</td></tr>')
    return "".join(out) + "</table>"

def games_table():
    lim = NOW + 36 * 3600
    gs = [g for g in D["games"] if datetime.fromisoformat(g["close"].replace("Z", "+00:00")).timestamp() <= lim]
    if not gs: return "<p style='color:#777;font-size:13px'>36時間以内の試合マーケットはありません。</p>"
    out = [f'<table cellspacing="0" cellpadding="0" width="100%"><tr><th {TH}>リーグ</th><th {TH}>日時(JST)</th><th {TH}>ホーム</th><th {THR}>勝率</th><th {TH}>アウェイ</th><th {THR}>勝率</th></tr>']
    for g in gs:
        if len(g["outcomes"]) != 2: continue
        h, a = g["outcomes"]
        t = datetime.fromisoformat((g.get("start") or g["close"]).replace("Z", "+00:00")).astimezone(JST).strftime("%-m/%-d %H:%M")
        bh = "font-weight:700;color:#2b3f7a" if (h["prob"] or 0) >= (a["prob"] or 0) and h["prob"] is not None else ""
        ba = "font-weight:700;color:#2b3f7a" if (a["prob"] or 0) > (h["prob"] or 0) else ""
        out.append(f'<tr><td {TD}>{e(g["league_ja"])}</td><td {TDR}>{t}</td><td {TD} style="{bh}">{e(oname(h))}</td><td {TDR}>{pct(h["prob"])}</td><td {TD} style="{ba}">{e(oname(a))}</td><td {TDR}>{pct(a["prob"])}</td></tr>')
    return "".join(out) + "</table>"

H2 = 'style="font-size:17px;margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid #1a1c25;font-family:Georgia,\'Hiragino Mincho ProN\',serif"'
parts = [f'''<div style="font-family:-apple-system,'Helvetica Neue','Hiragino Sans','Noto Sans JP',Arial,sans-serif;color:#1a1c25;max-width:760px;margin:0 auto;padding:16px;background:#fff">
<div style="font-size:11px;letter-spacing:.14em;color:#777">OVERSEAS PREDICTION MARKETS · JAPAN WATCH</div>
<h1 style="font-size:22px;margin:4px 0 6px;font-family:Georgia,'Hiragino Mincho ProN',serif">日本関連 海外オッズ 日報 {today.strftime("%Y年%-m月%-d日")}</h1>
<p style="font-size:12.5px;color:#555;margin:0 0 6px">データ取得 {D["generated_at_jst"]} ／ 追跡 {len(D["events"])}マーケット・{sum(len(x["outcomes"]) for x in D["events"])}選択肢 ／ Polymarket・Kalshi・Manifold</p>
{f'<p style="font-size:13px;margin:0"><a href="{e(SITE)}" style="color:#2b3f7a">▶ 一覧サイト（時系列チャート付き）を開く</a></p>' if SITE else ''}
<p style="font-size:12px;color:#666;background:#f3f4f7;padding:8px 10px;border-left:3px solid #2b3f7a;margin:12px 0 0">確率＝各市場のYES価格、倍率＝欧州式オッズ（1÷確率、的中時の払戻倍率）。「賭けを見る」で実際のサイト、「日本語訳」でGoogle翻訳経由の日本語ページへ。変化幅は確率のポイント差で、<span style="color:#c8302a">上昇＝赤</span>・<span style="color:#1d7a4f">下落＝緑</span>。Manifoldはプレイマネーのため参考値。</p>''']
parts.append(f'<h2 {H2}>24時間で動いた賭け</h2>' + mover_table(mv24, "prob_24h"))
parts.append(f'<h2 {H2}>7日間で動いた賭け</h2>' + mover_table(mv7, "prob_7d"))
for scope, head, lead in (("japan", "🎌 日本に関わる賭け", "首位の選択肢と倍率、2〜5位、関連ニュース。"), ("global", "🌐 海外で人気の賭け", "世界の予測市場で資金が集中している注目マーケット（分野ごとに抜粋）。")):
    sevs = [ev for ev in D["events"] if (ev.get("scope") or "japan") == scope]
    if not sevs: continue
    parts.append(f'<h2 style="font-size:19px;margin:34px 0 4px;font-family:Georgia,\'Hiragino Mincho ProN\',serif;border-left:4px solid #2b3f7a;padding-left:10px">{head}</h2><p style="font-size:12px;color:#666;margin:0 0 6px">{lead}</p>')
    groups = {}
    for ev in sevs: groups.setdefault(ev["cat"], []).append(ev)
    for k, c in CATS.items():
        if k in groups: parts.append(f'<h2 {H2}>{c["icon"]} {e(c["ja"])}</h2>' + cat_table(groups[k]))
parts.append(f'<h2 {H2}>直近の試合（36時間以内）</h2>' + games_table())
parts.append('<p style="font-size:11px;color:#888;margin-top:28px;line-height:1.7">本メールは情報の整理を目的とした自動配信で、賭博への参加を勧めるものではありません。日本国内からの海外賭博サイト利用には法的リスクがあります。配信停止はGitHubリポジトリのワークフローを無効化してください。</p></div>')

os.makedirs(os.path.join(ROOT, "digest"), exist_ok=True)
open(os.path.join(ROOT, "digest", "email.html"), "w", encoding="utf-8").write("".join(parts))
# 件名: 24hの最大変動 + 出来高首位
subj = f'【海外オッズ日報】{today.strftime("%-m/%-d")}'
if mv24:
    ev, o = mv24[0]; subj += f' {ev["title_ja"][:22]}：{oname(o, ev)} {pct(o["prob"])}（{(o["prob"]-o["prob_24h"])*100:+.0f}pt）'
big = max((x for x in D["events"] if x["source"] != "manifold" and x.get("scope") != "global" and not x["title_ja"].startswith("【関連】")), key=lambda x: x["volume"] or 0, default=None)
if big:
    t = sorted(big["outcomes"], key=lambda o: -(o["prob"] or 0))[0]; subj += f' ／ {big["title_ja"][:22]}：{oname(t, big)} {pct(t["prob"])}'
open(os.path.join(ROOT, "digest", "subject.txt"), "w", encoding="utf-8").write(subj)
print("subject:", subj); print("email.html:", os.path.getsize(os.path.join(ROOT, "digest", "email.html")) // 1024, "KB")
