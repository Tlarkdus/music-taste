"""곡 수집: 장르 태그별 상위곡 → 곡/아티스트 가중 태그 → data/taste.db. 중단돼도 다시 실행하면 이어받음."""
import sys
sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 cp949 깨짐 방지
import json
import re
import sqlite3
import time
from pathlib import Path

import requests
from config import LASTFM_API_KEY

URL = "https://ws.audioscrobbler.com/2.0/"
DB = Path(__file__).resolve().parent / "data" / "taste.db"
SEED_TAGS = ["pop", "k-pop", "hip-hop", "rnb", "rock", "indie", "electronic", "latin",
             "jazz", "metal", "folk", "classical", "punk", "soul", "country", "dance",
             "alternative", "house", "ambient", "singer-songwriter", "j-pop"]
# Last.fm은 한국 곡이 얇아 한국 태그를 넓게 따로 넣음 (tag.getInfo로 곡 수가 충분한 것만 추림)
KOREAN_TAGS = ["k-pop", "korean", "k-indie", "korean hip-hop", "kpop", "korean pop", "k-rock", "korean rock", "k-rnb", "krnb",
               "k-rap", "korean rap", "khh", "k-ballad", "korean ballad", "trot", "korean indie", "k-folk",
               "k-chart"]  # Last.fm 태그가 아니라 chart.py가 넣는 국내 차트 1위곡 표시
SEED_TAGS += [t for t in KOREAN_TAGS if t not in SEED_TAGS]
PER_TAG = 200


def _norm(s):
    s = s.lower()
    s = re.sub(r"[\(\[].*?[\)\]]", "", s)             # (Remastered), [Live] 등
    s = re.sub(r"\b(feat|ft|featuring)\b.*", "", s)   # feat. 이후
    return re.sub(r"[\W_]+", "", s)                   # 공백·기호 제거 (유니코드 문자는 유지)


def match_key(artist, track):
    return _norm(artist) + "|" + _norm(track)


def call(**params):
    """성공하면 JSON dict, 네트워크/5xx로 끝내 실패하면 None (다음 실행 때 재시도되도록 구분)."""
    for attempt in range(3):
        try:
            r = requests.get(URL, params={**params, "api_key": LASTFM_API_KEY, "format": "json"}, timeout=10)
            if r.status_code < 500:
                time.sleep(0.25)
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 * (attempt + 1))
    return None


def weighted_tags(resp):
    """getTopTags 응답 → [[태그, 가중치(0~100)], ...] 상위 30개."""
    tags = (resp.get("toptags") or {}).get("tag") or []
    return json.dumps([[t["name"].lower(), int(t["count"])] for t in tags[:30] if int(t["count"]) > 0], ensure_ascii=False)


def main():
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS tracks (match_key TEXT PRIMARY KEY, artist TEXT, track TEXT,
            seed_tag TEXT, rank_in_tag INTEGER, tags TEXT);
        CREATE TABLE IF NOT EXISTS artist_tags (artist TEXT PRIMARY KEY, tags TEXT);
        CREATE TABLE IF NOT EXISTS seeds_done (tag TEXT PRIMARY KEY);""")

    # 1) 시드: 태그별 상위곡 목록
    for tag in SEED_TAGS:
        if con.execute("SELECT 1 FROM seeds_done WHERE tag=?", (tag,)).fetchone():
            continue
        rank, ok = 0, True
        for page in range(1, PER_TAG // 100 + 1):
            resp = call(method="tag.getTopTracks", tag=tag, limit=100, page=page)
            if resp is None:
                ok = False
                break
            for t in (resp.get("tracks") or {}).get("track") or []:
                rank += 1
                con.execute("INSERT OR IGNORE INTO tracks VALUES (?,?,?,?,?,NULL)",
                            (match_key(t["artist"]["name"], t["name"]), t["artist"]["name"], t["name"], tag, rank))
        if ok:
            con.execute("INSERT INTO seeds_done VALUES (?)", (tag,))
        con.commit()
        print(f"시드 {tag:<18} {rank}곡", flush=True)

    # 2) 곡별 가중 태그
    todo = con.execute("SELECT match_key, artist, track FROM tracks WHERE tags IS NULL").fetchall()
    print(f"곡 태그 수집 대상 {len(todo)}곡", flush=True)
    for i, (key, artist, track) in enumerate(todo, 1):
        resp = call(method="track.getTopTags", artist=artist, track=track)
        if resp is not None:
            con.execute("UPDATE tracks SET tags=? WHERE match_key=?", (weighted_tags(resp), key))
        if i % 100 == 0:
            con.commit()
            print(f"  곡 {i}/{len(todo)}", flush=True)
    con.commit()

    # 3) 아티스트 가중 태그 (곡 태그가 빈 경우의 보완용)
    todo = [r[0] for r in con.execute(
        "SELECT DISTINCT artist FROM tracks WHERE artist NOT IN (SELECT artist FROM artist_tags)")]
    print(f"아티스트 태그 수집 대상 {len(todo)}팀", flush=True)
    for i, artist in enumerate(todo, 1):
        resp = call(method="artist.getTopTags", artist=artist)
        if resp is not None:
            con.execute("INSERT OR REPLACE INTO artist_tags VALUES (?,?)", (artist, weighted_tags(resp)))
        if i % 100 == 0:
            con.commit()
            print(f"  아티스트 {i}/{len(todo)}", flush=True)
    con.commit()

    n, pending, empty = con.execute("SELECT COUNT(*), SUM(tags IS NULL), SUM(tags='[]') FROM tracks").fetchone()
    print(f"\n완료: 총 {n}곡, 태그 미수집 {pending}곡, 곡 태그 없음 {empty}곡, "
          f"아티스트 {con.execute('SELECT COUNT(*) FROM artist_tags').fetchone()[0]}팀", flush=True)


if __name__ == "__main__":
    assert match_key("Coldplay", "Yellow (Remastered 2011)") == match_key("coldplay", "Yellow") == "coldplay|yellow"
    assert match_key("Drake", "One Dance feat. Wizkid") == "drake|onedance"
    assert match_key("아이유", "밤편지") == "아이유|밤편지"
    main()
