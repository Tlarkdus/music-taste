"""대결 후보곡 + 축 점수 → web/data.js (정적 페이지가 그대로 읽음). embed.py, enrich.py 이후 실행."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import json
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parent
CAP = 160  # 구역(클러스터)별 후보곡 상한
CHART_CAP = 80  # 그중 국내 차트곡 몫의 상한


def pct(x):
    """후보곡 안에서의 백분위 (0~1). 축마다 중앙값이 0.5가 되게."""
    return (rankdata(x) - 0.5) / len(x)


def main():
    z = np.load(ROOT / "data" / "emb.npz")
    pos = {str(k): i for i, k in enumerate(z["keys"])}
    con = sqlite3.connect(ROOT / "data" / "taste.db")

    seed = dict(con.execute("SELECT match_key, seed_tag FROM tracks"))
    clusters = []
    for c in range(int(z["labels"].max()) + 1):
        top = Counter(seed[k] for k, i in pos.items() if z["labels"][i] == c and k in seed).most_common(2)  # 임베딩 뒤 DB에서 지운 곡은 건너뜀
        clusters.append(" · ".join(s for s, n in top if n >= top[0][1] * 0.5))

    rows = [r for r in con.execute("""
        SELECT match_key, artist, track, listeners, substr(release_date, 1, 4), preview_url, artwork_url, itunes_url
        FROM enrich JOIN tracks USING(match_key) WHERE preview_url IS NOT NULL AND listeners IS NOT NULL""") if r[0] in pos]
    # 구역별 상한: 큰 구역(가요·K-pop)이 대결을 독차지하지 않게. 리스너 수 순으로 고르게 솎아 대중성 분포는 유지
    by_c = {}
    for r in sorted(rows, key=lambda r: r[3]):
        by_c.setdefault(int(z["labels"][pos[r[0]]]), []).append(r)
    thin = lambda g, n: [g[j] for j in sorted({round(x) for x in np.linspace(0, len(g) - 1, min(n, len(g)))})] if n > 0 else []
    rows = []
    for g in by_c.values():  # 국내 차트곡을 먼저 남기고, 남는 자리를 나머지 곡으로 채움
        chart = thin([r for r in g if seed[r[0]] == "k-chart"], CHART_CAP)
        rows += chart + thin([r for r in g if seed[r[0]] != "k-chart"], CAP - len(chart))
    idx = np.array([pos[r[0]] for r in rows])
    xy = z["xy"][idx]
    xy = (xy - xy.min(0)) / np.ptp(xy, 0)
    energy, popular, era = pct(z["energy"][idx]), pct([r[3] for r in rows]), pct([int(r[4]) for r in rows])

    tracks = [{
        "a": r[1], "t": r[2], "yr": int(r[4]), "p": r[5], "img": (r[6] or "").replace("100x100", "300x300"), "u": r[7],
        "c": int(z["labels"][i]), "x": round(float(xy[n, 0]), 3), "y": round(float(xy[n, 1]), 3),
        "ax": [round(float(energy[n]), 3), round(float(popular[n]), 3), round(float(era[n]), 3)],  # 신남, 대중, 최신
        "v": [round(float(v), 3) for v in z["E"][i]],
    } for n, (r, i) in enumerate(zip(rows, idx))]

    out = ROOT / "web" / "data.js"
    out.parent.mkdir(exist_ok=True)
    out.write_text("window.DATA = " + json.dumps({"clusters": clusters, "tracks": tracks}, ensure_ascii=False) + ";\n",
                   encoding="utf-8")
    print(f"{len(tracks)}곡 → {out} ({out.stat().st_size // 1024} KB)")
    print("클러스터:", clusters)
    print("클러스터별 후보곡 수:", sorted(Counter(t["c"] for t in tracks).items()))


if __name__ == "__main__":
    main()
