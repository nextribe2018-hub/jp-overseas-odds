#!/usr/bin/env python3
"""海外予測市場（Polymarket / Kalshi / Manifold）から日本関連マーケットの
現在の掛け率と価格履歴を取得し、data/latest.json と data/snapshots.jsonl に保存する。

使い方:  python3 fetch_odds.py            # 取得のみ
         python3 fetch_odds.py && python3 build_site.py   # 取得してサイト生成
"""
import json, os, re, sys, time, urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(ROOT, "config", "watchlist.json"), encoding="utf-8"))
NAMES = json.load(open(os.path.join(ROOT, "config", "names_ja.json"), encoding="utf-8"))
DATA = os.path.join(ROOT, "data")
NOW = int(time.time())
JST = timezone(timedelta(hours=9))

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
MANIFOLD = "https://api.manifold.markets/v0"

def get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "jp-odds-tracker/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == retries - 1:
                print("  HTTP", e.code, url, file=sys.stderr); return None
            time.sleep(1.5 * (i + 1))
        except Exception as e:
            if i == retries - 1:
                print("  ERR", e, url, file=sys.stderr); return None
            time.sleep(1.5 * (i + 1))

def ja(name):
    """選択肢名の日本語訳（辞書にあれば）"""
    if name in NAMES: return NAMES[name]
    for k, v in NAMES.items():
        if k.lower() == name.lower(): return v
    return None

def translate_url(url):
    """Google 翻訳プロキシ（translate.goog）で日本語表示するURL"""
    try:
        u = urllib.parse.urlsplit(url)
        host = u.netloc.replace("-", "--").replace(".", "-") + ".translate.goog"
        q = (u.query + "&" if u.query else "") + "_x_tr_sl=auto&_x_tr_tl=ja&_x_tr_hl=ja"
        return urllib.parse.urlunsplit((u.scheme, host, u.path, q, u.fragment))
    except Exception:
        return url

def fetch_news(query, n=3):
    """Google ニュース（日本語）RSS から関連ニュース上位 n 件"""
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(query) + "&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            x = r.read().decode("utf-8", "replace")
    except Exception as e:
        print("  news ERR", query, e, file=sys.stderr); return []
    import html as _html
    out = []
    for it in re.findall(r"<item>(.*?)</item>", x, re.S)[:n]:
        def g(tag):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S)
            return _html.unescape(re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1))).strip() if m else ""
        title, src = g("title"), g("source")
        if src and title.endswith(" - " + src): title = title[: -len(src) - 3]
        try:
            from email.utils import parsedate_to_datetime
            ts = int(parsedate_to_datetime(g("pubDate")).timestamp())
        except Exception:
            ts = None
        out.append({"title": title, "link": g("link"), "source": src, "ts": ts})
    return out

def f(x, default=None):
    try: return float(x)
    except (TypeError, ValueError): return default

def thin(hist, max_pts=400):
    """履歴を最大 max_pts 点に間引く（先頭・末尾は必ず残す）"""
    hist = sorted({int(t): p for t, p in hist if p is not None}.items())
    if len(hist) <= max_pts: return [[t, round(p, 4)] for t, p in hist]
    step = len(hist) / (max_pts - 1)
    out = [hist[int(i * step)] for i in range(max_pts - 1)] + [hist[-1]]
    return [[t, round(p, 4)] for t, p in out]

def build_review(ev, news_all):
    """結果が出たマーケットの検証データ: 節目のオッズと、オッズを大きく動かした日＋前後のニュース"""
    outs = sorted(ev["outcomes"], key=lambda o: -(o.get("prob") or 0))
    winners = set(ev.get("winners") or [])
    outs.sort(key=lambda o: (0 if o["key"] in winners else 1, -(o.get("prob") or 0)))
    outs = outs[:4]
    def at(h, t):
        past = [p for tt, p in h if tt <= t]
        return past[-1] if past else None
    rows, moves = [], []
    for o in outs:
        h = o.get("history") or []
        if not h: continue
        t_end = h[-1][0]
        # 「直前」= 結果確定で 0/1 に張り付く前の最後の実勢価格
        pre = None
        for tt, p in reversed(h[:-1]):
            if 0.01 < p < 0.99: pre = p; break
        if pre is None: pre = at(h, t_end - 3 * 3600)
        final = o["prob"] if (o.get("closed") and o.get("prob") is not None) else h[-1][1]
        rows.append({"key": o["key"], "name": o.get("name_ja") or o["name"], "won": o["key"] in winners,
                     "final": final, "pre": pre, "d1": at(h, t_end - 86400), "d7": at(h, t_end - 7 * 86400), "d30": at(h, t_end - 30 * 86400)})
        # 日次の終値で変化を見る
        daily = {}
        for tt, p in h: daily[int(tt // 86400)] = (tt, p)
        days = sorted(daily)
        for a, b in zip(days, days[1:]):
            d = daily[b][1] - daily[a][1]
            if abs(d) >= 0.03 and 0.01 < daily[b][1] < 0.99 or (abs(d) >= 0.08):
                near = [n for n in news_all if abs(n["ts"] - daily[b][0]) <= 2 * 86400]
                near.sort(key=lambda n: abs(n["ts"] - daily[b][0]))
                moves.append({"t": daily[b][0], "key": o["key"], "name": o.get("name_ja") or o["name"], "delta": round(d, 4),
                              "before": round(daily[a][1], 4), "after": round(daily[b][1], 4), "news": near[:3]})
    moves.sort(key=lambda m: -abs(m["delta"]))
    # 同じ日の重複は最大の変化のみ
    seen, top = set(), []
    for m in moves:
        k = (int(m["t"] // 86400), m["key"])
        if k in seen: continue
        seen.add(k); top.append(m)
    return {"rows": rows, "moves": top[:6]}

def select_outcomes(outcomes, item):
    """keep（キーワード一致）と top（上位N件）で選択肢を絞る。指定なしなら全件。"""
    keep = item.get("keep"); top = item.get("top")
    if not keep and not top: return outcomes
    ranked = sorted(outcomes, key=lambda o: -(o["prob"] or 0))
    chosen, seen = [], set()
    if top:
        for o in ranked[:top]:
            chosen.append(o); seen.add(o["key"])
    if keep:
        for o in outcomes:
            if o["key"] not in seen and any(k.lower() in o["name"].lower() for k in keep):
                chosen.append(o); seen.add(o["key"])
    return chosen

# ---------------- Polymarket ----------------
def pm_history(token_id):
    h = get(f"{CLOB}/prices-history?market={token_id}&interval=max&fidelity=1440") or {}
    pts = [[x["t"], x["p"]] for x in h.get("history", [])]
    h2 = get(f"{CLOB}/prices-history?market={token_id}&interval=1w&fidelity=60") or {}
    pts += [[x["t"], x["p"]] for x in h2.get("history", [])]
    return pts

def fetch_polymarket(item):
    ev = get(f"{GAMMA}/events/{item['id']}")
    if not ev: return None
    outs = []
    for m in ev.get("markets", []):
        try:
            prices = json.loads(m.get("outcomePrices") or "[]")
            toks = json.loads(m.get("clobTokenIds") or "[]")
            names = json.loads(m.get("outcomes") or "[]")
        except Exception:
            prices, toks, names = [], [], []
        if not prices: continue
        name = m.get("groupItemTitle") or m.get("question")
        vol, liq, p0 = f(m.get("volumeNum"), 0) or 0, f(m.get("liquidityNum"), 0) or 0, f(prices[0], 0.5)
        closed = bool(m.get("closed"))
        if re.fullmatch(r"(Person|Player|Team|Candidate) [A-Z0-9]+", name or "") and not vol:
            continue  # プレースホルダー選択肢を除外
        if not closed and not vol and (not liq or abs(p0 - 0.5) < 0.02):
            continue  # 未成立（取引・流動性なし、価格0.5固定）の選択肢を除外
        outs.append({
            "key": f"pm:{m['id']}", "name": name, "name_ja": ja(name),
            "question": m.get("question"),
            "prob": f(prices[0]), "bid": None, "ask": f(m.get("bestAsk")),
            "volume": round(f(m.get("volumeNum"), 0) or 0),
            "token": toks[0] if toks else None,
            "binary_labels": names,
            "end": m.get("endDate"),
            "closed": closed, "won": (closed and f(prices[0], 0) >= 0.99) or None,
        })
    outs = select_outcomes(outs, item)
    with ThreadPoolExecutor(6) as ex:
        hists = list(ex.map(lambda o: pm_history(o["token"]) if o["token"] else [], outs))
    for o, h in zip(outs, hists):
        o["history"] = thin(h); o.pop("token", None)
    return {
        "key": f"polymarket:{ev['id']}", "source": "polymarket",
        "title": ev.get("title"), "title_ja": item.get("title_ja"), "cat": item["cat"],
        "url": f"https://polymarket.com/event/{ev.get('slug')}",
        "volume": round(f(ev.get("volume"), 0) or 0), "volume24h": round(f(ev.get("volume24hr"), 0) or 0),
        "liquidity": round(f(ev.get("liquidity"), 0) or 0),
        "end": ev.get("endDate"), "description": (ev.get("description") or "")[:600],
        "n_total": len(ev.get("markets", [])), "outcomes": outs,
        "closed": bool(ev.get("closed")) or (bool(outs) and all(o["closed"] for o in outs)),
    }

# ---------------- Kalshi ----------------
def kalshi_history(series, ticker):
    pts = []
    for days, interval in ((365, 1440), (7, 60)):
        c = get(f"{KALSHI}/series/{series}/markets/{ticker}/candlesticks?start_ts={NOW - days*86400}&end_ts={NOW}&period_interval={interval}") or {}
        for x in c.get("candlesticks", []):
            p = x.get("price", {}) or {}
            v = f(p.get("close_dollars")) or f(p.get("previous_dollars"))
            if v is None:
                yb, ya = f((x.get("yes_bid") or {}).get("close_dollars")), f((x.get("yes_ask") or {}).get("close_dollars"))
                if yb is not None and ya is not None and (yb or ya): v = (yb + ya) / 2
            if v is not None: pts.append([x["end_period_ts"], v])
    return pts

def kalshi_outcome(m, series):
    yb, ya = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars"))
    last = f(m.get("last_price_dollars"))
    spread = (ya - yb) if (yb is not None and ya is not None) else None
    if spread is not None and ya > 0 and spread <= 0.1:
        prob = (yb + ya) / 2          # 板が薄くなければ仲値
    elif last:
        prob = last                   # 直近約定
    elif spread is not None and spread <= 0.2 and ya > 0:
        prob = (yb + ya) / 2
    else:
        prob = None                   # 未成立（取引なし・板が広すぎる）
    name = m.get("yes_sub_title") or m.get("title")
    return {
        "key": f"ks:{m['ticker']}", "name": name, "name_ja": ja(name), "question": m.get("title"),
        "prob": prob, "bid": yb, "ask": ya, "last": last,
        "volume": round(f(m.get("volume_fp"), 0) or 0), "end": m.get("close_time"),
        "closed": m.get("status") in ("settled", "finalized", "closed", "determined"),
        "won": True if m.get("result") == "yes" else (False if m.get("result") == "no" else None),
        "_series": series, "_ticker": m["ticker"],
    }

def fetch_kalshi(item):
    r = get(f"{KALSHI}/events/{item['id']}?with_nested_markets=true")
    if not r or "event" not in r: return None
    ev = r["event"]; series = ev.get("series_ticker")
    outs = [kalshi_outcome(m, series) for m in ev.get("markets", []) if m.get("status") in ("active", "open", "initialized", "settled", "finalized", "closed", "determined")]
    for o in outs:
        if o["closed"] and o["won"] is not None: o["prob"] = 1.0 if o["won"] else 0.0
    outs = select_outcomes(outs, item)
    with ThreadPoolExecutor(6) as ex:
        hists = list(ex.map(lambda o: kalshi_history(o["_series"], o["_ticker"]), outs))
    for o, h in zip(outs, hists):
        o["history"] = thin(h); o.pop("_series"); o.pop("_ticker")
    return {
        "key": f"kalshi:{ev['event_ticker']}", "source": "kalshi",
        "title": ev.get("title"), "title_ja": item.get("title_ja"), "cat": item["cat"],
        "url": f"https://kalshi.com/markets/{series.lower()}/{ev['event_ticker'].lower()}" if series else "https://kalshi.com",
        "volume": sum(o["volume"] for o in outs), "volume24h": None, "liquidity": None,
        "end": max((o["end"] or "" for o in outs), default=None),
        "description": (ev.get("sub_title") or ""), "n_total": len(ev.get("markets", [])), "outcomes": outs,
        "closed": bool(outs) and all(o["closed"] for o in outs),
    }

def fetch_kalshi_games(gs, days=4):
    """直近の試合マーケット（NPB / Jリーグ など）"""
    r = get(f"{KALSHI}/events?series_ticker={gs['series']}&status=open&limit=200&with_nested_markets=true") or {}
    games = []
    limit = datetime.now(timezone.utc) + timedelta(days=days)
    for ev in r.get("events", []):
        if gs.get("must") and gs["must"] not in ev["event_ticker"]: continue
        ms = ev.get("markets", [])
        if not ms: continue
        try: close = datetime.fromisoformat(ms[0]["close_time"].replace("Z", "+00:00"))
        except Exception: continue
        if close > limit: continue
        outs = [kalshi_outcome(m, gs["series"]) for m in ms]
        for o in outs: o.pop("_series"); o.pop("_ticker"); o["history"] = []
        games.append({
            "key": f"kalshi:{ev['event_ticker']}", "source": "kalshi", "cat": gs["cat"], "league_ja": gs["label_ja"],
            "title": ev.get("title"), "title_ja": " vs ".join(o["name_ja"] or o["name"] for o in outs) if len(outs) == 2 else ev.get("title"),
            "url": f"https://kalshi.com/markets/{gs['series'].lower()}/{ev['event_ticker'].lower()}",
            "start": ms[0].get("expected_expiration_time") or ms[0]["close_time"], "close": ms[0]["close_time"],
            "volume": sum(o["volume"] for o in outs), "outcomes": outs,
        })
    games.sort(key=lambda g: g["close"])
    return games

# ---------------- Manifold ----------------
def fetch_manifold(item):
    m = get(f"{MANIFOLD}/market/{item['id']}")
    if not m: return None
    bets = get(f"{MANIFOLD}/bets?contractId={item['id']}&limit=1000") or []
    outs = []
    if m.get("outcomeType") == "BINARY":
        hist = [[b["createdTime"] // 1000, b["probAfter"]] for b in bets if b.get("probAfter") is not None]
        hist.append([NOW, m.get("probability")])
        res = m.get("resolution")
        outs.append({"key": f"mf:{m['id']}", "name": "Yes", "name_ja": "はい（YES）", "question": m["question"],
                     "prob": (1.0 if res == "YES" else 0.0 if res == "NO" else m.get("probability")), "bid": None, "ask": None, "volume": round(m.get("volume") or 0),
                     "end": None, "history": thin(hist), "closed": bool(m.get("isResolved")),
                     "won": (True if res == "YES" else False if res == "NO" else None) if m.get("isResolved") else None})
    elif m.get("outcomeType") in ("MULTIPLE_CHOICE",):
        for a in m.get("answers", []):
            if a.get("text") == "Other" and a.get("probability", 0) < 0.02: continue
            hist = [[b["createdTime"] // 1000, b["probAfter"]] for b in bets if b.get("answerId") == a["id"] and b.get("probAfter") is not None]
            hist.append([NOW, a.get("probability")])
            outs.append({"key": f"mf:{m['id']}:{a['id']}", "name": a["text"], "name_ja": ja(a["text"]), "question": m["question"],
                         "prob": a.get("probability"), "bid": None, "ask": None, "volume": None, "end": None, "history": thin(hist),
                         "closed": bool(m.get("isResolved")), "won": (a.get("resolution") == "YES" or (a.get("probability") or 0) >= 0.99) if m.get("isResolved") else None})
        outs = select_outcomes(outs, item)
    else:
        return None
    close = m.get("closeTime")
    return {
        "key": f"manifold:{m['id']}", "source": "manifold",
        "title": m["question"], "title_ja": item.get("title_ja"), "cat": item["cat"], "url": m.get("url"),
        "volume": round(m.get("volume") or 0), "volume24h": round(m.get("volume24Hours") or 0), "liquidity": round(m.get("totalLiquidity") or 0),
        "traders": m.get("uniqueBettorCount"),
        "end": datetime.fromtimestamp(close / 1000, timezone.utc).isoformat() if close else None,
        "description": (m.get("textDescription") or "")[:600], "n_total": len(outs),
        "sum_to_one": m.get("shouldAnswersSumToOne", True), "outcomes": outs, "closed": bool(m.get("isResolved")),
    }

FETCHERS = {"polymarket": fetch_polymarket, "kalshi": fetch_kalshi, "manifold": fetch_manifold}

def main():
    os.makedirs(os.path.join(DATA, "snapshots"), exist_ok=True)
    events = []
    for item in CFG["items"]:
        print(f"[{item['source']}] {item['id']} {item.get('title_ja','')}")
        try:
            ev = FETCHERS[item["source"]](item)
        except Exception as e:
            print("   FAILED", e, file=sys.stderr); ev = None
        if ev and ev["outcomes"]:
            ev["_order"] = len(events); ev["scope"] = item.get("scope", "japan")
            ev["url_ja"] = translate_url(ev["url"])
            ev["news_q"] = item.get("news_q") or item.get("title_ja") or ev["title"]
            ev["news_url"] = "https://news.google.com/search?q=" + urllib.parse.quote(ev["news_q"]) + "&hl=ja&gl=JP&ceid=JP:ja"
            events.append(ev)
        else:
            print("   -> no data", file=sys.stderr)
    print("[news] 関連ニュースを取得")
    with ThreadPoolExecutor(6) as ex:
        for ev, news in zip(events, ex.map(lambda e: fetch_news(e["news_q"], 5), events)):
            ev["news"] = news[:3]
    # 蓄積: data/news_log.json（key → [{ts,title,link,source}]、link で重複排除、最大80件）
    log_path = os.path.join(DATA, "news_log.json")
    try: news_log = json.load(open(log_path, encoding="utf-8"))
    except Exception: news_log = {}
    for ev in events:
        lst = news_log.setdefault(ev["key"], [])
        seen = {n.get("link") for n in lst}
        for n in ev.get("news") or []:
            if n.get("link") and n["link"] not in seen and n.get("ts"):
                lst.append({"ts": n["ts"], "title": n["title"], "link": n["link"], "source": n.get("source", "")}); seen.add(n["link"])
        lst.sort(key=lambda n: n["ts"]); del lst[:-80]
    json.dump(news_log, open(log_path, "w", encoding="utf-8"), ensure_ascii=False)
    games = []
    for gs in CFG.get("game_series", []):
        print(f"[games] {gs['series']}")
        try: games += fetch_kalshi_games(gs)
        except Exception as e: print("   FAILED", e, file=sys.stderr)

    # ---- アーカイブ: 結果が出た（全選択肢が終了した）マーケットは data/archive.json に保存し続ける
    arch_path = os.path.join(DATA, "archive.json")
    try: archive = json.load(open(arch_path, encoding="utf-8"))
    except Exception: archive = {}
    still_open = []
    for ev in events:
        if ev.get("closed"):
            ev["status"] = "resolved"
            winners = [o for o in ev["outcomes"] if o.get("won") or (o.get("prob") or 0) >= 0.99]
            ev["winners"] = [o["key"] for o in winners]
            prev = archive.get(ev["key"])
            end_ts = None
            try:
                end_ts = int(datetime.fromisoformat((ev.get("end") or "").replace("Z", "+00:00")).timestamp())
            except Exception:
                pass
            ev["resolved_at"] = prev.get("resolved_at") if prev and prev.get("resolved_at") else (end_ts if end_ts and end_ts < NOW else NOW)
            ev["news"] = ev.get("news") or (prev.get("news") if prev else [])
            for o in ev["outcomes"]: o["history"] = thin(o.get("history", []), 200)
            try:
                nl = json.load(open(os.path.join(DATA, "news_log.json"), encoding="utf-8")).get(ev["key"], [])
            except Exception:
                nl = []
            if prev and prev.get("news_all"):
                have = {n["link"] for n in nl}; nl += [n for n in prev["news_all"] if n["link"] not in have]; nl.sort(key=lambda n: n["ts"])
            ev["news_all"] = nl[-80:]
            ev["review"] = build_review(ev, ev["news_all"])
            archive[ev["key"]] = ev
        else:
            ev["status"] = "open"; still_open.append(ev)
    events = still_open
    json.dump(archive, open(arch_path, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[archive] {len(archive)} resolved markets kept")

    # ---- 自前スナップショット（実行のたびに追記 → 独自の時系列）
    snap_path = os.path.join(DATA, "snapshots.jsonl")
    with open(snap_path, "a", encoding="utf-8") as fp:
        for ev in events:
            for o in ev["outcomes"]:
                if o["prob"] is not None:
                    fp.write(json.dumps({"t": NOW, "k": o["key"], "p": round(o["prob"], 4)}) + "\n")
        for g in games:
            for o in g["outcomes"]:
                if o["prob"] is not None:
                    fp.write(json.dumps({"t": NOW, "k": o["key"], "p": round(o["prob"], 4)}) + "\n")
    # スナップショットを履歴にマージ
    snaps = {}
    for line in open(snap_path, encoding="utf-8"):
        try: s = json.loads(line)
        except Exception: continue
        snaps.setdefault(s["k"], []).append([s["t"], s["p"]])
    for coll in (events, games):
        for ev in coll:
            for o in ev["outcomes"]:
                o["history"] = thin(o.get("history", []) + snaps.get(o["key"], []))
                o["snapshots"] = snaps.get(o["key"], [])[-200:]
                # 変化率（24h / 7d）
                h = o["history"]
                def at(sec):
                    past = [p for t, p in h if t <= NOW - sec]
                    return past[-1] if past else None
                o["prob_24h"] = at(86400); o["prob_7d"] = at(7 * 86400); o["prob_30d"] = at(30 * 86400)

    out = {
        "generated_at": NOW, "generated_at_jst": datetime.fromtimestamp(NOW, JST).strftime("%Y-%m-%d %H:%M JST"),
        "categories": CFG["categories"], "events": events, "games": games,
        "archive": sorted(archive.values(), key=lambda e: (-(e.get("volume") or 0) if e.get("source") != "manifold" else 0, -(e.get("resolved_at") or 0))),
        "sources": {
            "polymarket": {"name": "Polymarket", "note": "米国発の分散型予測市場（USDC建て）。価格＝YESの暗黙確率。"},
            "kalshi": {"name": "Kalshi", "note": "米CFTC規制下の予測市場取引所（ドル建て）。価格＝YESの暗黙確率。"},
            "manifold": {"name": "Manifold", "note": "プレイマネー（マナ）の予測市場。実資金ではないため参考値。"},
        },
    }
    json.dump(out, open(os.path.join(DATA, "latest.json"), "w", encoding="utf-8"), ensure_ascii=False)
    # 日次アーカイブ
    json.dump(out, open(os.path.join(DATA, "snapshots", datetime.fromtimestamp(NOW, JST).strftime("%Y%m%d_%H%M") + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"done: {len(events)} events, {len(games)} games, {sum(len(e['outcomes']) for e in events)} outcomes -> data/latest.json")

if __name__ == "__main__":
    main()
