"""가상 사용자로 테스트의 측정 성능을 검증한다.

페이지(web/index.html)의 출제(nextPair)·채점(score)·판정(bits)을 그대로 옮기고,
진짜 취향을 아는 가상 사용자에게 테스트를 풀게 해서 판정이 맞는지 본다.

    py -u analysis/sim.py            # 전체 (몇 분)
    py -u analysis/sim.py quick      # 사용자 수를 줄여 빠르게
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
raw = (ROOT / "web" / "data.js").read_text(encoding="utf-8")
DATA = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
T = DATA["tracks"]
AX = np.array([t["ax"] for t in T])          # (N, 3) 신남·대중·최신, 순위 정규화라 각 축이 0~1 균등
V = np.array([t["v"] for t in T])            # (N, 32) 단위 벡터
C = np.array([t["c"] for t in T])
N, K = len(T), len(DATA["clusters"])
ROUNDS = 12
QUICK = "quick" in sys.argv
USERS = 400 if QUICK else 2000


# ---------- 페이지 로직 이식 ----------

def next_pair(pool, axis, rng, smart=True):
    """index.html nextPair(): 무작위 40쌍 중 |목표 축 차이| + 소리 유사도가 가장 큰 쌍.
    smart: True = 페이지 그대로, False = 아무 쌍, "axis" = 목표 축 차이만 (비교용)"""
    a = pool[rng.integers(len(pool), size=40)]
    b = pool[rng.integers(len(pool), size=40)]
    ok = a != b
    a, b = a[ok], b[ok]
    if smart is False:
        return a[0], b[0]
    sc = np.abs(AX[a, axis] - AX[b, axis])
    if smart is True:
        sc = sc + np.einsum("ij,ij->i", V[a], V[b])
    j = int(np.argmax(sc))                      # JS는 '>'로 첫 최댓값을 유지 — argmax와 같음
    return a[j], b[j]


def score(rounds, frac):
    """index.html score(): 소리 축 3개 = 0.5 + 평균(이긴 곡 - 진 곡), 폭 = frac / 0.8."""
    w = np.array([r[0] for r in rounds]); l = np.array([r[1] for r in rounds])
    s = np.clip(0.5 + (AX[w] - AX[l]).mean(axis=0), 0, 1)
    return np.append(s, np.clip(frac / 0.8, 0, 1))


# ---------- 가상 사용자 ----------

def make_user(rng, theta=None):
    """theta: 소리 축 3개의 진짜 위치(0~1, 0.5 초과면 그쪽을 좋아함), breadth: 좋아하는 장르 비율, g: 장르 취향 방향."""
    th = rng.uniform(0, 1, 3) if theta is None else np.asarray(theta, float)
    g = rng.normal(size=V.shape[1]); g /= np.linalg.norm(g)
    return {"theta": th, "breadth": rng.uniform(0, 1), "g": g}


def utility(u, idx, beta, genre):
    # 축 취향(2θ-1 ∈ [-1, 1])이 β로, 장르 취향이 genre로 효용에 들어감. genre는 축 측정에 대한 방해 요인
    return beta * (AX[idx] - 0.5) @ (2 * u["theta"] - 1) + genre * V[idx] @ u["g"]


def take_test(u, rng, beta=4.0, genre=1.0, rounds_n=ROUNDS, smart=True):
    pool = np.arange(N)
    rounds = []
    for r in range(rounds_n):
        if len(pool) < 2:
            break
        a, b = next_pair(pool, r % 3, rng, smart)
        pool = pool[(pool != a) & (pool != b)]
        p = 1 / (1 + np.exp(-(utility(u, a, beta, genre) - utility(u, b, beta, genre))))
        rounds.append((a, b) if rng.random() < p else (b, a))
    # 폭 질문: 장르마다 타일 하나, 각 타일을 breadth 확률로 고름 (index.html showGrid의 장르당 1곡 구성)
    shown = len({int(c) for c in C[pool]})
    likes = rng.binomial(shown, u["breadth"])
    return score(rounds, likes / shown)


def truth(u):
    return np.append(u["theta"] >= 0.5, u["breadth"] >= 0.4)   # 페이지 기준: 폭은 장르 40% 이상이면 '넓게'


# ---------- 실험 ----------

def run(beta=4.0, genre=1.0, rounds_n=ROUNDS, smart=True, users=USERS, seed=0):
    rng = np.random.default_rng(seed)
    hit, margin, retest, full = [], [], [], []
    for _ in range(users):
        u = make_user(rng)
        b1 = take_test(u, rng, beta, genre, rounds_n, smart) >= 0.5
        b2 = take_test(u, rng, beta, genre, rounds_n, smart) >= 0.5
        t = truth(u)
        hit.append(b1 == t)
        full.append((b1 == t).all())
        retest.append((b1 == b2).all())
        margin.append(np.abs(u["theta"] - 0.5))
    hit = np.array(hit); margin = np.array(margin)
    return {"axis_acc": hit.mean(0), "type_acc": np.mean(full), "retest": np.mean(retest),
            "hit": hit, "margin": margin}


def fmt(xs):
    return " ".join(f"{x:.2f}" for x in xs)


if __name__ == "__main__":
    print(f"곡 {N}개, 장르 구역 {K}개, 사용자 {USERS}명/조건\n")
    names = ["신남", "대중", "최신", "넓게"]

    print("[1] 축별 정확도 · 유형 전체 정확도 · 재검사 일치율 (대결 12회, 장르 잡음 1.0)")
    print(f"{'β':>4} | {' '.join(f'{n:>4}' for n in names)} | 유형 정확도 | 재검사 같은 유형")
    base = None
    for beta in (1, 2, 4, 8):
        r = run(beta=beta)
        base = r if beta == 4 else base
        print(f"{beta:>4} | {fmt(r['axis_acc'])} | {r['type_acc']:>10.2f} | {r['retest']:>14.2f}")

    print("\n[2] 취향이 뚜렷할수록 잘 맞히는가 (β=4, 소리 축 3개 합산)")
    m, h = base["margin"].ravel(), base["hit"][:, :3].ravel()
    for lo, hi in ((0, .1), (.1, .2), (.2, .3), (.3, .5)):
        sel = (m >= lo) & (m < hi)
        print(f"  |θ−0.5| {lo:.1f}~{hi:.1f}: 정확도 {h[sel].mean():.2f}  (n={sel.sum()})")

    print("\n[3] 대결 횟수별 소리 축 평균 정확도 (β=4)")
    for n in (6, 9, 12, 16, 20):
        r = run(rounds_n=n, users=USERS // 2)
        print(f"  {n:>2}회: {r['axis_acc'][:3].mean():.3f}  재검사 {r['retest']:.2f}")

    print("\n[4] 출제 방식 비교 (β=4, 12회)")
    for smart, label in ((True, "현재(축 차이+소리 유사도)"), ("axis", "축 차이만"), (False, "무작위 쌍")):
        r = run(smart=smart)
        print(f"  {label:<16}: 소리 축 {fmt(r['axis_acc'][:3])} 평균 {r['axis_acc'][:3].mean():.3f}"
              f"  유형 {r['type_acc']:.2f}  재검사 {r['retest']:.2f}")
    # 소리 유사도 항이 축 차이를 덮는지: 후보 쌍에서 두 항의 크기 비교
    rng = np.random.default_rng(2)
    a, b = rng.integers(N, size=(2, 5000))
    print(f"  후보 쌍 평균 — |축 차이| {np.abs(AX[a, 0] - AX[b, 0]).mean():.2f}, 소리 유사도 {np.einsum('ij,ij->i', V[a], V[b]).mean():.2f}"
          f" (표준편차 {np.abs(AX[a, 0] - AX[b, 0]).std():.2f} / {np.einsum('ij,ij->i', V[a], V[b]).std():.2f})")

    print("\n[5] 취향 없는 사람(θ=0.5, 장르 잡음만)은 어느 쪽으로 판정되나 — 0.50이 이상적")
    rng = np.random.default_rng(1)
    bits = np.array([take_test(make_user(rng, [.5, .5, .5]), rng) >= 0.5 for _ in range(USERS)])
    print(f"  '오른쪽'(신남·대중·최신·넓게) 판정 비율: {fmt(bits.mean(0))}")
