"""README용 그림 2장. sim.py와 같은 시뮬레이션을 돌려 PNG로 저장한다.

    py -u analysis/plot.py      # 몇 분
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sim import run, USERS

OUT = Path(__file__).resolve().parent
NEW, OLD, RAND = "#2a78d6", "#eb6834", "#898781"     # 검증한 팔레트 1·2번 + 무작위 기준선은 회색
INK, INK2, GRID, AXIS, SURF = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False, "font.size": 10,
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": .8,
})


def style(ax, title):
    ax.set_title(title, loc="left", color=INK, fontsize=11, fontweight="bold", pad=10)
    ax.tick_params(length=0)


# ---------- 그림 1: 대결 횟수별 정확도 · 재검사 ----------
ROUNDS = [6, 9, 12, 16, 20]
methods = [("axis", "축 차이만 (현재)", NEW, "-"), (True, "축 차이 + 소리 유사도 (예전)", OLD, "-"),
           (False, "무작위 쌍", RAND, "--")]
res = {m: [run(rounds_n=n, smart=m, users=USERS // 2, seed=10 + n) for n in ROUNDS] for m, *_ in methods}

fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
for ax, key, title, fmt in (
        (axes[0], lambda r: r["axis_acc"][:3].mean(), "소리 축 정확도", "{:.2f}"),
        (axes[1], lambda r: r["retest"], "다시 해도 같은 유형이 나올 확률", "{:.2f}")):
    for m, label, color, ls in methods:
        ys = [key(r) for r in res[m]]
        ax.plot(ROUNDS, ys, ls, color=color, lw=2, marker="o", ms=5, mec=SURF, mew=1.5, label=label, zorder=3)
        if m is not False:                      # 무작위 기준선은 끝값 라벨 생략 (예전 방식과 겹침, 범례로 충분)
            ax.annotate(fmt.format(ys[-1]), (ROUNDS[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                        va="center", color=INK2, fontsize=9)
    style(ax, title)
    ax.set_xticks(ROUNDS)
    ax.set_xlabel("대결 횟수")
    ax.set_xlim(5, 22)
# 헤드라인: 재검사 일치율은 현재 12회가 예전 20회보다 높다
y_new12, y_old20 = res["axis"][2]["retest"], res[True][4]["retest"]
axes[1].annotate(f"현재 12회 {y_new12:.2f}\n> 예전 20회 {y_old20:.2f}", xy=(12, y_new12), xytext=(12.6, .29),
                 color=INK, fontsize=9, arrowprops=dict(arrowstyle="-", color=INK2, lw=.8))
axes[0].legend(loc="lower right", frameon=False, fontsize=9)
fig.suptitle(f"출제 방식별 측정 성능 (가상 사용자 {USERS // 2:,}명 × 조건, β=4)", x=.01, ha="left", color=INK2, fontsize=9)
fig.tight_layout(rect=(0, 0, 1, .96))
fig.savefig(OUT / "fig_rounds.png", dpi=160)
print("saved fig_rounds.png")

# ---------- 그림 2: 취향이 뚜렷할수록 잘 맞히는가 ----------
r = run(smart="axis", seed=3)
m, h = r["margin"].ravel(), r["hit"][:, :3].ravel()
edges = np.linspace(0, .5, 11)
mid = (edges[:-1] + edges[1:]) / 2
acc = np.array([h[(m >= lo) & (m < hi)].mean() for lo, hi in zip(edges[:-1], edges[1:])])
n = np.array([((m >= lo) & (m < hi)).sum() for lo, hi in zip(edges[:-1], edges[1:])])
se = np.sqrt(acc * (1 - acc) / n)

fig, ax = plt.subplots(figsize=(6.4, 4))
ax.axhline(.5, color=AXIS, lw=1, ls="--", zorder=1)
ax.text(.5, .49, "동전 던지기 (0.5)", color=INK2, fontsize=8.5, va="top", ha="right")
ax.errorbar(mid, acc, yerr=1.96 * se, fmt="o-", color=NEW, lw=2, ms=5, mec=SURF, mew=1.5,
            ecolor=NEW, elinewidth=1, capsize=0, zorder=3)
ax.annotate(f"{acc[0]:.2f}", (mid[0], acc[0]), xytext=(9, -2), textcoords="offset points", va="center", color=INK2, fontsize=9)
ax.annotate(f"{acc[-1]:.2f}", (mid[-1], acc[-1]), xytext=(0, -14), textcoords="offset points", ha="center", color=INK2, fontsize=9)
style(ax, "취향이 뚜렷할수록 정확하게 판정한다")
ax.set_xlabel("진짜 취향이 기준선에서 떨어진 정도  |θ - 0.5|")
ax.set_ylabel("판정 정확도")
ax.set_ylim(.4, 1.02)
ax.set_xlim(-.01, .51)
fig.text(.01, .01, f"소리 축 3개 합산, 축 차이만 출제, 대결 12회, β=4, 가상 사용자 {USERS:,}명 · 오차 막대 95% 구간",
         color=INK2, fontsize=8)
fig.tight_layout(rect=(0, .04, 1, 1))
fig.savefig(OUT / "fig_margin.png", dpi=160)
print("saved fig_margin.png")
