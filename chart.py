"""국내 차트 곡 추가: 영문 위키백과의 가온/써클 디지털 차트 연도별 1위곡 목록 → tracks (seed_tag='k-chart').
Last.fm 태그만으로는 해외 K-pop 팬 취향에 쏠려서 국내 히트곡을 따로 넣음. 사용: py chart.py → 이어서 collect.py, enrich.py."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import io
import re
import sqlite3
import time

import pandas as pd
import requests
from collect import DB, match_key

YEARS = range(2010, 2026)


def clean_song(s):
    s = re.sub(r"\[.*?\]|[†‡*]", "", str(s))        # 각주, 연간 1위 표시
    m = re.search(r'"(.+?)"', s)                     # "Up & Down" (위아래) → Up & Down
    return (m.group(1) if m else s).strip()


def clean_artist(s):
    s = re.sub(r"\[.*?\]", "", str(s))
    return re.split(r"\s+(?:featuring|feat\.?|and|with|&|x)\s+|,", s, flags=re.I)[0].strip()  # 대표 아티스트만 (Last.fm·iTunes 조회용)


def fetch(year):
    for name in ("Circle", "Gaon"):
        for attempt in range(4):
            r = requests.get("https://en.wikipedia.org/w/api.php", headers={"User-Agent": "chart-fetch/0.1"}, timeout=20, params={
                "action": "parse", "page": f"List of {name} Digital Chart number ones of {year}", "prop": "text", "format": "json", "redirects": 1})
            time.sleep(2)
            if r.status_code == 200:
                break
            time.sleep(20)  # 429 등: 쉬었다 재시도
        else:
            raise SystemExit(f"{year}: 위키백과 응답 실패 ({r.status_code})")  # 일부 연도만 빠진 채 진행되지 않게
        html = r.json().get("parse", {}).get("text", {}).get("*")
        if html:
            break
    else:
        return set()
    out = set()
    for df in pd.read_html(io.StringIO(html)):
        cols = {str(c).split("(")[0].strip().lower(): c for c in df.columns}
        if "song" in cols and "artist" in cols:      # 주간·월간 표 모두
            out |= {(clean_artist(a), clean_song(s)) for s, a in zip(df[cols["song"]], df[cols["artist"]])}
    return {(a, s) for a, s in out if a and s and a != "nan" and s != "nan"}


def main():
    con = sqlite3.connect(DB, timeout=300)
    n = 0
    for y in YEARS:
        songs = fetch(y)
        for a, s in songs:
            # rank 1: enrich.py의 한국 보강(상위 KOREAN_TOP)에 전부 들어가도록
            n += con.execute("INSERT OR IGNORE INTO tracks VALUES (?,?,?,?,?,NULL)", (match_key(a, s), a, s, "k-chart", 1)).rowcount
        print(f"{y}: {len(songs)}곡", flush=True)
    con.execute("INSERT OR IGNORE INTO seeds_done VALUES ('k-chart')")
    con.commit()
    print(f"새로 추가 {n}곡 (이미 있던 곡 제외)")


if __name__ == "__main__":
    assert clean_song('"Up & Down" (위아래)') == "Up & Down" and clean_song('"Ditto" †') == "Ditto"
    assert clean_artist("Jonghyun featuring Zion.T") == "Jonghyun" and clean_artist("Gain and Jo Kwon") == "Gain"
    assert clean_artist("Rosé and Bruno Mars[1]") == "Rosé"
    if "dry" in sys.argv:
        s = sorted(fetch(2015)); print(len(s), s[:40])
    else:
        main()
