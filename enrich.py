"""대결 후보곡 보강: Last.fm 리스너 수(대중성 축) + iTunes 발매일(시대 축)·30초 미리듣기·앨범아트.
사용: py -u enrich.py [곡수=720]  — 장르별 순위를 고르게 훑는 순서로 처리, 다시 실행하면 이어받음.
매칭 규칙이 바뀌면 V를 올리고 다시 실행 → 옛 규칙으로 받은 곡의 iTunes 정보만 다시 받음."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import re
import sqlite3
import time

import requests
from collect import DB, KOREAN_TAGS, _norm, call

V = 3  # iTunes 매칭 규칙 버전 (2: 변형판 제외 + 가장 오래된 발매본, 3: 한글/영문 표기가 다른 한국 곡 매칭)
KOREAN_TOP = 35  # 한국 태그는 태그별 상위 이만큼을 전부 후보로 (한국 곡 보강)
VARIANT = re.compile(r"\b(remix|remixed|mix|live|karaoke|instrumental|cover|tribute|acoustic|version|ver|japanese|edit|demo|sped|slowed|re-?record(ed|ing)?)\b", re.I)
HANGUL, LATIN = re.compile(r"[가-힣]"), re.compile(r"[a-z]")


def same_title(mine, theirs):
    """제목 일치. Last.fm의 '독 Poison'처럼 한글·영문이 함께 적힌 제목은 iTunes 쪽이 그 일부('Poison')여도 인정."""
    a, b = _norm(mine), _norm(theirs)
    return bool(a) and (a == b or bool(len(b) >= 2 and b in a and HANGUL.search(a) and LATIN.search(a)))


def pick(results, artist, track):
    """검색 결과 중 같은 곡을 골라 원곡에 가장 가까운 것 반환. 없으면 {}.
    _norm이 괄호를 지워서 'Lady (… Remix)'도 같은 곡으로 잡히므로, 변형판은 원제에 그 말이 없으면 뒤로 미루고
    남은 것 중 발매일이 가장 이른 것을 고름(재발매·컴필레이션보다 원래 발매본)."""
    prefer = lambda xs: [x for x in xs if VARIANT.search(track) or not VARIANT.search(x["trackName"])] or xs
    ok = [x for x in results if x.get("previewUrl") and x.get("releaseDate") and same_title(track, x.get("trackName", ""))]
    a = _norm(artist)
    strict = [x for x in ok if a in _norm(x.get("artistName", "")) or _norm(x.get("artistName", "")) in a]
    if strict:
        return min(prefer(strict), key=lambda x: x["releaseDate"])
    # '소녀시대' ↔ "Girls' Generation"처럼 표기 문자가 다르면 이름 비교가 불가능 → 검색 순위가 가장 높은 것을 믿음
    loose = [x for x in ok if bool(HANGUL.search(a)) != bool(HANGUL.search(_norm(x.get("artistName", ""))))]
    return prefer(loose)[0] if loose else {}


def itunes(artist, track):
    """일치하는 곡 dict, 없으면 {}, 네트워크/차단으로 확인 못 했으면 None."""
    for country in ("US", "KR"):  # 한국 곡은 US 스토어에서 아티스트명이 영문이라 KR로 한 번 더
        for attempt in range(3):
            try:
                r = requests.get("https://itunes.apple.com/search", timeout=10, params={
                    "term": f"{artist} {track}", "entity": "song", "limit": 25, "country": country})
                time.sleep(3)  # iTunes 권장 한도 분당 약 20회
                if r.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(60)  # 403/429 = 속도 제한 → 쉬었다 재시도
        else:
            return None
        hit = pick(r.json().get("results", []), artist, track)
        if hit:
            return hit
    return {}


def main(limit):
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS enrich (match_key TEXT PRIMARY KEY, listeners INTEGER, playcount INTEGER,
        release_date TEXT, preview_url TEXT, artwork_url TEXT, itunes_url TEXT)""")
    if "v" not in [c[1] for c in con.execute("PRAGMA table_info(enrich)")]:
        con.execute("ALTER TABLE enrich ADD COLUMN v INTEGER DEFAULT 1")
    done = con.execute("SELECT COUNT(*) FROM enrich").fetchone()[0]
    stale = con.execute("SELECT match_key, artist, track, 1 FROM enrich JOIN tracks USING(match_key) WHERE v < ?", (V,)).fetchall()
    new = con.execute("""SELECT match_key, artist, track, 0 FROM tracks
        WHERE match_key NOT IN (SELECT match_key FROM enrich)
        ORDER BY (rank_in_tag - 1) % 7, rank_in_tag LIMIT ?""", (max(limit - done, 0),)).fetchall()
    marks = ",".join("?" * len(KOREAN_TAGS))
    korean = con.execute(f"""SELECT match_key, artist, track, 0 FROM tracks
        WHERE seed_tag IN ({marks}) AND rank_in_tag <= ? AND match_key NOT IN (SELECT match_key FROM enrich)
        ORDER BY rank_in_tag""", (*KOREAN_TAGS, KOREAN_TOP)).fetchall()
    new += [r for r in korean if r not in new]
    todo = new if "new" in sys.argv else stale + new  # 'new': 재조회는 미루고 새 곡만 (급할 때)
    print(f"이미 {done}곡 (그중 iTunes 다시 받을 곡 {len(stale)}), 새로 {len(new)}곡 (한국 보강 {len(korean)})", flush=True)
    for i, (key, artist, track, is_stale) in enumerate(todo, 1):
        it = itunes(artist, track)
        if it is None:
            continue  # 다음 실행 때 재시도
        fields = (it.get("releaseDate"), it.get("previewUrl"), it.get("artworkUrl100"), it.get("trackViewUrl"), V)
        if is_stale and not it:  # 새 규칙으로 못 찾으면 기존에 받아둔 정보를 지우지 않고 유지
            con.execute("UPDATE enrich SET v=? WHERE match_key=?", (V, key))
        elif is_stale:
            con.execute("UPDATE enrich SET release_date=?, preview_url=?, artwork_url=?, itunes_url=?, v=? WHERE match_key=?",
                        (*fields, key))
        else:
            lf = call(method="track.getInfo", artist=artist, track=track)
            if lf is None:
                continue
            info = lf.get("track", {})
            con.execute("INSERT OR REPLACE INTO enrich VALUES (?,?,?,?,?,?,?,?)", (
                key, int(info["listeners"]) if "listeners" in info else None,
                int(info["playcount"]) if "playcount" in info else None, *fields))
        if i % 25 == 0:
            con.commit()
            print(f"  {i}/{len(todo)}", flush=True)
    con.commit()
    print("완료:", con.execute("SELECT COUNT(*), COUNT(listeners), COUNT(preview_url) FROM enrich").fetchone(),
          "(전체, 리스너 있음, 미리듣기 있음)", flush=True)


if __name__ == "__main__":
    _r = lambda name, date: {"trackName": name, "artistName": "Modjo", "releaseDate": date, "previewUrl": "u"}
    _res = [_r("Lady (Hear Me Tonight) [Sparrow Remix]", "1999-01-01"), _r("Lady (Hear Me Tonight)", "2010-05-05"),
            _r("Lady (Hear Me Tonight)", "2000-06-19"), _r("Other Song", "1990-01-01")]
    assert pick(_res, "Modjo", "Lady (Hear Me Tonight)")["releaseDate"] == "2000-06-19"   # 리믹스 제외 + 가장 이른 발매본
    assert pick(_res[:1], "Modjo", "Lady (Hear Me Tonight)")["releaseDate"] == "1999-01-01"  # 변형판뿐이면 그것이라도
    assert pick(_res, "Modjo", "Nope") == {}
    _k = [{"trackName": "Gee", "artistName": "Girls' Generation", "releaseDate": "2009-01-05", "previewUrl": "u"}]
    assert pick(_k, "소녀시대", "Gee") and not pick(_k, "Someone Else", "Gee")             # 표기 문자가 다를 때만 이름 비교 생략
    assert same_title("독 Poison", "Poison") and not same_title("사랑했지만", "사랑")       # 섞어 쓴 제목만 부분 일치 허용
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 720)
