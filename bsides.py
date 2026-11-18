"""한국 아티스트의 수록곡 추가: 후보에 있는 한국 아티스트의 Last.fm 인기곡 중 상위(타이틀곡)를 건너뛰고 그 아래 곡을 넣음.
태그 상위곡·차트 1위곡만으로는 후보가 타이틀곡뿐이라 디깅/대중 축이 얕아지기 때문. 사용: py -u bsides.py → collect.py, enrich.py.
ponytail: '수록곡' 판정은 아티스트 내 인기 순위뿐이라 옛 타이틀곡이 섞임. 정확히 하려면 앨범 트랙리스트(MusicBrainz) 필요."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import json
import sqlite3

from collect import DB, KOREAN_TAGS, call, match_key
from embed import KR_TAG
from enrich import VARIANT

ARTISTS, SKIP, PER_ARTIST = 150, 8, 2  # 리스너 많은 순 아티스트 수, 건너뛸 상위곡 수, 아티스트당 넣을 곡 수
BSIDE_RANK = 0  # rank_in_tag=0을 수록곡 표시로 씀 (enrich.py의 한국 보강 조건 rank <= KOREAN_TOP에도 걸림)


def choose(names, have):
    """인기순 곡명 목록에서 상위 SKIP개를 건너뛰고, 변형판·이미 있는 곡을 뺀 앞쪽 PER_ARTIST개."""
    out = []
    for name in names[SKIP:]:
        key = match_key("", name)
        if not VARIANT.search(name) and key != "|" and key not in have:
            out.append(name)
            have = have | {key}
        if len(out) == PER_ARTIST:
            break
    return out


def main():
    con = sqlite3.connect(DB)
    marks = ",".join("?" * len(KOREAN_TAGS))
    rows = con.execute(f"""SELECT t.artist, MIN(t.seed_tag), COALESCE(a.tags, '[]') FROM enrich JOIN tracks t USING(match_key)
        LEFT JOIN artist_tags a USING(artist) WHERE preview_url IS NOT NULL AND seed_tag IN ({marks})
        GROUP BY t.artist ORDER BY MAX(COALESCE(listeners, 0)) DESC""", KOREAN_TAGS).fetchall()
    # 한국 태그가 없는 아티스트는 동명이인(Turbo=폴란드 메탈 밴드)일 수 있어 제외 → 엉뚱한 곡이 들어오는 것 방지
    rows = [r for r in rows if any(KR_TAG.search(n) for n, _ in json.loads(r[2]))][:ARTISTS]
    n = 0
    for i, (artist, seed, _) in enumerate(rows, 1):
        resp = call(method="artist.getTopTracks", artist=artist, limit=30)
        names = [t["name"] for t in ((resp or {}).get("toptracks") or {}).get("track") or []]
        have = {k.split("|", 1)[1] for (k,) in con.execute("SELECT match_key FROM tracks WHERE artist=?", (artist,))}
        for name in choose(names, {"|" + h for h in have}):
            n += con.execute("INSERT OR IGNORE INTO tracks VALUES (?,?,?,?,?,NULL)", (
                match_key(artist, name), artist, name, "korean" if seed == "k-chart" else seed, BSIDE_RANK)).rowcount
        if i % 25 == 0:
            con.commit()
            print(f"  아티스트 {i}/{len(rows)}, 추가 {n}곡", flush=True)
    con.commit()
    print(f"수록곡 추가 {n}곡 (아티스트 {len(rows)}팀)", flush=True)


if __name__ == "__main__":
    _names = [f"T{i}" for i in range(8)] + ["Ditto (250 Remix)", "Old One", "ASAP", "Get Up"]
    assert choose(_names, {"|oldone"}) == ["ASAP", "Get Up"]  # 상위 8곡·리믹스·이미 있는 곡 제외
    main()
