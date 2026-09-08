#!/usr/bin/env python3
"""Claude（Opus 5）でマーケットごとのAI解説を生成し、
 - 全マーケット分を data/ai_comments.json に保持（ページに埋め込み、掲示板を開いた時に投稿される）
 - その日の注目マーケット（日本関連3件＋海外2件）だけ Firestore の掲示板へ自動投稿
ANTHROPIC_API_KEY が無い場合は何もしない。"""
import json, os, sys, time, hashlib, math, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
STATE_PATH = os.path.join(DATA, "ai_comments.json")
MODEL = "claude-opus-5"
JST = timezone(timedelta(hours=9))
NOW = int(time.time())
MAX_GENERATE = int(os.environ.get("AI_MAX_GENERATE", "40"))   # 1回の実行で生成する上限（コスト保護）
AUTO_JP, AUTO_GLOBAL = 3, 2                                    # 自動投稿する件数

def load(path, default):
    try: return json.load(open(path, encoding="utf-8"))
    except Exception: return default

def oname(o, ev):
    if o.get("name_ja"): return o["name_ja"]
    if len(ev["outcomes"]) == 1 and o["name"] and len(o["name"]) > 24: return "はい（YES）"
    return o["name"]

def pct(p): return "—" if p is None else f"{p*100:.1f}%"
def odds(p): return "—" if not p else f"{min(999, 1/p):.2f}倍"
def digest(text): return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

def market_brief(ev):
    """モデルに渡す材料（オッズ・変化・ニュース）"""
    outs = sorted(ev["outcomes"], key=lambda o: -(o["prob"] or 0))[:5]
    lines = [f"マーケット: {ev['title_ja']}（原題: {ev['title']}）", f"取引所: {ev['source']} ／ 出来高: {ev.get('volume')} ／ 締切: {ev.get('end')}"]
    if ev.get("description"): lines.append("ルール要約: " + ev["description"][:300].replace("\n", " "))
    lines.append("選択肢と現在の市場確率（倍率）・24h変化・7日変化:")
    for o in outs:
        d24 = "" if o.get("prob_24h") is None or o["prob"] is None else f" 24h {((o['prob']-o['prob_24h'])*100):+.1f}pt"
        d7 = "" if o.get("prob_7d") is None or o["prob"] is None else f" 7日 {((o['prob']-o['prob_7d'])*100):+.1f}pt"
        lines.append(f"- {oname(o, ev)}: {pct(o['prob'])}（{odds(o['prob'])}）{d24}{d7}")
    if ev.get("status") == "resolved":
        wins = [oname(o, ev) for o in ev["outcomes"] if o["key"] in (ev.get("winners") or [])]
        lines.append("結果: " + ("、".join(wins) if wins else "該当なし（NO）"))
        # 終了30日前の価格
        for o in outs[:3]:
            h = o.get("history") or []
            if h:
                t_end = h[-1][0]; past = [p for t, p in h if t <= t_end - 30 * 86400]
                if past: lines.append(f"  {oname(o, ev)} の30日前の価格: {pct(past[-1])} → 最終 {pct(h[-1][1])}")
    news = ev.get("news") or []
    if news:
        lines.append("関連ニュース（日本語・新しい順）:")
        for n in news[:3]:
            d = datetime.fromtimestamp(n["ts"], JST).strftime("%-m/%-d") if n.get("ts") else ""
            lines.append(f"- [{d} {n.get('source','')}] {n['title']}")
    return "\n".join(lines)

SYSTEM = """あなたは海外の予測市場（Polymarket / Kalshi / Manifold）の掛け率を日本の読者向けに解説するアナリストです。掲示板への最初の書き込みとして、議論の呼び水になる短い解説を書きます。

守ること:
- 日本語、です・ます調、全体で220〜300字。見出しや箇条書き記号は使わず、段落は最大2つ。
- 首位の選択肢がなぜその確率（倍率）なのかを、与えられたニュースと価格変化から説明する。次に、対抗となる選択肢に賭ける側の根拠や、確率が動く可能性のある材料を1〜2点挙げる。
- 与えられた材料にない事実を作らない。ニュースを引用するときは媒体名を添える。
- 「確実」「必ず」などの断定、賭けの推奨、投資助言はしない。最後に読者への問いかけを1文入れる。
- 結果が出たマーケットの場合は、事前の市場確率が結果をどの程度織り込んでいたかを振り返る（220字前後）。"""

def generate(client, ev):
    kind = "retro" if ev.get("status") == "resolved" else "preview"
    prompt = market_brief(ev) + ("\n\n上記のマーケットについて、掲示板の最初の書き込みとして解説を書いてください。" if kind == "preview" else "\n\n結果が出たこのマーケットについて、振り返りの書き込みを書いてください。")
    resp = client.messages.create(
        model=MODEL, max_tokens=2000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason == "refusal":
        return None, kind, resp.usage
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return text, kind, resp.usage

def fs_create_post(cfg, ev_key, text, ts_ms):
    """Firestore REST（匿名・ルールで制限）で掲示板に投稿"""
    url = f"https://firestore.googleapis.com/v1/projects/{cfg['projectId']}/databases/(default)/documents/posts?key={cfg['apiKey']}"
    body = {"fields": {
        "ev": {"stringValue": ev_key}, "out": {"stringValue": ""}, "name": {"stringValue": "AI解説（Claude）"},
        "text": {"stringValue": text}, "ts": {"integerValue": str(ts_ms)}, "likes": {"integerValue": "0"}, "by": {"stringValue": "claude"},
    }}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("name")

def needs_generation(ev, prev):
    if not prev: return "new"
    if ev.get("status") == "resolved":
        return None if prev.get("kind") == "retro" else "resolved"
    if NOW - prev.get("ts", 0) > 7 * 86400: return "stale"
    snap = prev.get("probs") or {}
    for o in ev["outcomes"]:
        p0 = snap.get(o["key"])
        if p0 is not None and o["prob"] is not None and abs(o["prob"] - p0) >= 0.05: return "moved"
    return None

def score(ev):
    """自動投稿する注目度: 24h変化・出来高・締切の近さ・ニュースの新しさ"""
    mv = max((abs((o["prob"] or 0) - o["prob_24h"]) for o in ev["outcomes"] if o.get("prob_24h") is not None and o["prob"] is not None), default=0)
    s = min(mv * 100, 30)
    s += math.log10((ev.get("volume") or 0) + 1) * 3 if ev["source"] != "manifold" else 0
    try:
        end = datetime.fromisoformat(ev["end"].replace("Z", "+00:00")).timestamp()
        if 0 < end - NOW < 7 * 86400: s += 10
    except Exception: pass
    fresh = [n for n in (ev.get("news") or []) if n.get("ts") and NOW - n["ts"] < 48 * 3600]
    s += min(len(fresh), 3) * 4
    return s

def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY が未設定のためAI解説はスキップ"); return
    import anthropic
    client = anthropic.Anthropic()
    latest = load(os.path.join(DATA, "latest.json"), None)
    if not latest: print("latest.json がありません"); return
    state = load(STATE_PATH, {"comments": {}, "posted": {}})
    comments, posted = state["comments"], state["posted"]
    fb = load(os.path.join(ROOT, "config", "firebase.json"), {})

    events = latest["events"] + latest.get("archive", [])
    todo = []
    for ev in events:
        why = needs_generation(ev, comments.get(ev["key"]))
        if why: todo.append((ev, why))
    todo.sort(key=lambda x: -score(x[0]))
    print(f"[ai] 生成対象 {len(todo)} 件（上限 {MAX_GENERATE}）")
    cost_in = cost_out = 0
    for ev, why in todo[:MAX_GENERATE]:
        try:
            text, kind, usage = generate(client, ev)
        except Exception as e:
            print("  ERR", ev["title_ja"], e, file=sys.stderr); continue
        if not text: print("  refused:", ev["title_ja"]); continue
        cost_in += usage.input_tokens + (getattr(usage, "cache_read_input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cost_out += usage.output_tokens
        comments[ev["key"]] = {"text": text, "kind": kind, "ts": NOW, "model": MODEL, "why": why, "hash": digest(text),
                               "probs": {o["key"]: o["prob"] for o in ev["outcomes"]}, "title_ja": ev["title_ja"]}
        print(f"  generated[{why}] {ev['title_ja'][:40]}")
    print(f"[ai] tokens in≈{cost_in} out≈{cost_out} → 概算 ${cost_in/1e6*5 + cost_out/1e6*25:.2f}")

    # ---- 自動投稿: 今日の注目（日本関連3 + 海外2）。未投稿の解説だけ。
    if fb.get("projectId"):
        cands = [ev for ev in latest["events"] if ev["key"] in comments and posted.get(ev["key"]) != comments[ev["key"]]["hash"]]
        cands.sort(key=lambda e: -score(e))
        pick = [e for e in cands if e.get("scope") != "global"][:AUTO_JP] + [e for e in cands if e.get("scope") == "global"][:AUTO_GLOBAL]
        for ev in pick:
            c = comments[ev["key"]]
            try:
                fs_create_post(fb, ev["key"], c["text"], NOW * 1000)
                posted[ev["key"]] = c["hash"]; c["auto_posted"] = NOW
                print("  posted:", ev["title_ja"][:40])
            except urllib.error.HTTPError as e:
                print("  post ERR", ev["title_ja"], e.code, e.read()[:200], file=sys.stderr)
            except Exception as e:
                print("  post ERR", ev["title_ja"], e, file=sys.stderr)
    state["updated_at"] = NOW
    json.dump(state, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[ai] 保持 {len(comments)} 件 / 自動投稿済み {len(posted)} 件 -> data/ai_comments.json")

if __name__ == "__main__":
    main()
