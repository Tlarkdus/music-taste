"""취향 지도: 가중 태그 → TF-IDF → SVD 임베딩 → KMeans 유형 후보. 사용: py embed.py [k]"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize

from scipy.stats import rankdata
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score

from collect import KOREAN_TAGS

DATA = Path(__file__).resolve().parent / "data"
MIN_DF, DIM = 15, 32
CALM = set("chill chillout mellow sad melancholy melancholic relaxing calm lofi easylistening sleep soft dreamy".split())
HYPE = set("party energetic upbeat catchy fun happy workout aggressive angry summer club banger".split())


def norm_tag(t):
    return re.sub(r"[\s\-_]+", "", t.lower())  # hip-hop / hip hop / hiphop 통합


KR_TAG = re.compile(r"korea|k-?pop|^k-|khh|trot")
NOT_KR = re.compile(r"j-?pop|japanese|j-?rock|anime|doujin|vtuber")
FOREIGN_OK = {"Dua Lipa", "Anne-Marie", "The Kid Laroi", "Idina Menzel"}  # 국내 차트 1위를 한 진짜 해외 아티스트


def fix_korean(artist, seed, ttags, atags):
    """한국 곡의 Last.fm 아티스트 태그 오류 보정. 영문 표기가 같은 해외 아티스트(Turbo=폴란드 메탈 밴드)의 태그가
    돌아오거나 한 페이지에 섞여 있어서(Loco=thrash metal+korean) 한국 곡이 메탈·J-pop 구역으로 가던 문제.
    ponytail: 태그 문자열 규칙 + 예외 이름 목록. 곡이 더 늘면 MusicBrainz ID로 아티스트를 특정하는 쪽으로."""
    if seed not in KOREAN_TAGS or artist in FOREIGN_OK:
        return ttags, atags
    if not any(KR_TAG.search(n) for n, _ in ttags + atags):
        atags = []                                                    # 한국 태그가 하나도 없음 → 동명이인의 태그
    atags = [[n, w] for n, w in atags if not NOT_KR.search(n)         # 일본 활동 때문에 붙은 태그
             and ("metal" not in n or "rock" in seed)]                # 섞여 들어온 메탈 태그 (K-록 시드는 그대로)
    if seed == "k-chart" and not ttags and not atags:
        atags = [["korean", 30], ["k-pop", 30]]                       # 태그가 없는 차트곡도 버리지 않고 가요 쪽에
    return ttags, atags


def load():
    con = sqlite3.connect(DATA / "taste.db")
    rows = con.execute("""SELECT t.match_key, t.artist, t.track, t.seed_tag, t.rank_in_tag, t.tags, COALESCE(a.tags, '[]')
                          FROM tracks t LEFT JOIN artist_tags a USING(artist)""").fetchall()
    artist_names = {norm_tag(r[1]) for r in rows}  # 'leessang' 같은 아티스트명 태그 제거용
    meta, feats = [], []
    for key, artist, track, seed, rank, ttags, atags in rows:
        ttags, atags = fix_korean(artist, seed, json.loads(ttags), json.loads(atags))
        if not ttags and not atags:
            continue
        d = defaultdict(float)
        for name, w in ttags:
            d[norm_tag(name)] += w / 100
        for name, w in atags:  # 곡 태그가 있으면 아티스트 태그는 절반만 반영
            d[norm_tag(name)] += (0.5 if ttags else 1.0) * w / 100
        if seed != "k-chart":  # 차트 1위는 장르가 아니라서 피처로 쓰면 발라드·힙합이 한 덩어리로 묶임
            d[norm_tag(seed)] += 0.3
        feats.append({k: v for k, v in d.items() if k not in artist_names})
        meta.append((key, artist, track, seed, rank))
    return meta, feats


def main():
    meta, feats = load()
    # 에너지 축 라벨(신남 - 잔잔함). 라벨에 쓴 분위기 태그는 임베딩 피처에서 빼서 CV가 누수 없이 나오게 함
    raw = np.array([sum(f.get(t, 0) for t in HYPE) - sum(f.get(t, 0) for t in CALM) for f in feats])
    feats = [{k: v for k, v in f.items() if k not in CALM | HYPE} for f in feats]
    vec = DictVectorizer()
    X = vec.fit_transform(feats)
    keep = np.asarray((X > 0).sum(0)).ravel() >= MIN_DF
    X, vocab = X[:, keep], np.array(vec.get_feature_names_out())[keep]
    # 가중치가 1 미만 소수라 sublinear_tf(1+log tf)를 쓰면 음수가 됨 → sqrt로 완만하게만 눌러줌
    T = TfidfTransformer().fit_transform(X.sqrt())
    df = np.asarray((X > 0).sum(0)).ravel()
    print("최빈 태그:", ", ".join(f"{vocab[i]}({df[i]})" for i in np.argsort(df)[::-1][:45]))
    E = normalize(TruncatedSVD(DIM, random_state=0).fit_transform(T))
    print(f"{len(meta)}곡, 태그 어휘 {len(vocab)}개 → {DIM}차원\n")

    # 분위기 태그가 있는 곡으로 '잔잔함→신남' 방향을 학습해 전체 곡에 점수 부여 (0=잔잔, 1=신남 백분위)
    m = raw != 0
    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    auc = cross_val_score(clf, E[m], raw[m] > 0, cv=5, scoring="roc_auc").mean()
    energy = rankdata(clf.fit(E[m], raw[m] > 0).decision_function(E)) / len(E)
    known = [i for i in np.argsort(energy) if meta[i][4] <= 15]  # 장르 내 15위 안의 아는 곡만 눈으로 확인
    print(f"에너지 축: 라벨 {m.sum()}곡 (신남 {(raw > 0).sum()} / 잔잔 {(raw < 0).sum()}), 5-fold AUC {auc:.3f}")
    print("  가장 잔잔:", " / ".join(f"{meta[i][1]} - {meta[i][2]}" for i in known[:10]))
    print("  가장 신남:", " / ".join(f"{meta[i][1]} - {meta[i][2]}" for i in known[-10:]), "\n")

    fits = {k: KMeans(k, n_init=10, random_state=0).fit(E) for k in range(4, 13)}
    sil = {k: silhouette_score(E, m.labels_) for k, m in fits.items()}
    print("silhouette:", "  ".join(f"k={k}:{s:.3f}" for k, s in sil.items()))
    k = int(sys.argv[1]) if len(sys.argv) > 1 else max(sil, key=sil.get)
    labels = fits[k].labels_ if k in fits else KMeans(k, n_init=10, random_state=0).fit_predict(E)
    print(f"→ k={k}\n")

    gmean = np.asarray(T.mean(0)).ravel()
    names = []
    for c in range(k):
        idx = np.where(labels == c)[0]
        top = vocab[np.argsort(np.asarray(T[idx].mean(0)).ravel() - gmean)[::-1][:6]]
        seeds = Counter(meta[i][3] for i in idx).most_common(3)
        ex = sorted(idx, key=lambda i: meta[i][4])[:6]
        names.append(f"{c}: {', '.join(top[:3])}")
        print(f"[{c}] {len(idx)}곡 | 태그: {', '.join(top)}")
        print(f"     시드: {', '.join(f'{s}({n})' for s, n in seeds)}")
        print(f"     예시: {' / '.join(f'{meta[i][1]} - {meta[i][2]}' for i in ex)}\n")

    P = TSNE(2, random_state=0, init="pca").fit_transform(E)
    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.figure(figsize=(11, 8))
    for c in range(k):
        m = labels == c
        plt.scatter(P[m, 0], P[m, 1], s=5, label=names[c])
    plt.legend(markerscale=4, fontsize=8, loc="best")
    plt.title(f"취향 지도 (t-SNE, k={k})")
    plt.axis("off")
    plt.savefig(DATA / "map.png", dpi=110, bbox_inches="tight")
    np.savez(DATA / "emb.npz", E=E, labels=labels, energy=energy, xy=P, keys=np.array([m[0] for m in meta]))


if __name__ == "__main__":
    assert norm_tag("Hip-Hop") == norm_tag("hip hop") == "hiphop"
    assert fix_korean("Turbo", "k-chart", [], [["heavy metal", 100], ["polish", 50]])[1] == [["korean", 30], ["k-pop", 30]]
    assert fix_korean("Bibi", "k-rnb", [], [["k-pop", 100], ["j-pop", 90], ["rnb", 80]])[1] == [["k-pop", 100], ["rnb", 80]]
    assert fix_korean("Dua Lipa", "k-chart", [], [["pop", 100]])[1] == [["pop", 100]]
    assert fix_korean("Turbo", "metal", [], [["heavy metal", 100]])[1] == [["heavy metal", 100]]  # 한국 시드가 아니면 그대로
    main()
