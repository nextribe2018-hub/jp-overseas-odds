#!/bin/zsh
# 日本関連 海外オッズ相場表 — データ再取得 → サイト再生成
cd "$(dirname "$0")"
python3 fetch_odds.py && python3 build_site.py && python3 make_digest.py
