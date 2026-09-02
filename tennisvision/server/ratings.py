"""Glicko-2 레이팅.

왜 Elo 가 아니라 Glicko-2 인가
    동호인 테니스는 경기 수가 적고 불규칙하다. Elo 는 "이 사람 실력을 얼마나
    확신하는가"를 표현하지 못해서, 3경기 한 사람과 100경기 한 사람을 같은
    자신감으로 매칭해 버린다. Glicko-2 는 레이팅과 함께 편차(RD)와 변동성을
    들고 다니므로
      - 신규 유저는 RD 가 커서 몇 경기 만에 제자리를 찾고,
      - 오래 쉰 유저는 RD 가 다시 벌어져 과도한 점수 이동을 막고,
      - 매칭에서 "이 매치업이 실제로 팽팽할 확률"을 계산할 수 있다.

테니스 특화 한 가지
    승/패만 쓰면 6-0 과 7-6 이 같아진다. 그래서 게임 획득 비율을 섞은
    `score_outcome()` 을 기본으로 쓴다(가중치 조절 가능, 순수 승패로도 사용 가능).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

SCALE = 173.7178
DEFAULT_RATING = 1500.0
DEFAULT_RD = 350.0
DEFAULT_VOL = 0.06
TAU = 0.5            # 변동성 변화 제약 (작을수록 보수적)
EPSILON = 1e-6


@dataclass
class Rating:
    rating: float = DEFAULT_RATING
    rd: float = DEFAULT_RD
    vol: float = DEFAULT_VOL

    @property
    def mu(self) -> float:
        return (self.rating - DEFAULT_RATING) / SCALE

    @property
    def phi(self) -> float:
        return self.rd / SCALE

    def interval95(self) -> tuple[float, float]:
        return (self.rating - 1.96 * self.rd, self.rating + 1.96 * self.rd)

    def copy(self) -> "Rating":
        return Rating(self.rating, self.rd, self.vol)


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi ** 2))


def _E(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def expected_score(a: Rating, b: Rating) -> float:
    """a 가 b 를 이길 확률(불확실성 포함)."""
    phi = math.sqrt(a.phi ** 2 + b.phi ** 2)
    return 1.0 / (1.0 + math.exp(-_g(phi) * (a.mu - b.mu)))


def score_outcome(won: bool, games_for: int, games_against: int, mov_weight: float = 0.25) -> float:
    """승패 + 게임 득실을 섞은 결과값 (0~1)."""
    total = games_for + games_against
    share = (games_for / total) if total else (1.0 if won else 0.0)
    base = 1.0 if won else 0.0
    s = (1.0 - mov_weight) * base + mov_weight * share
    return float(min(max(s, 0.02), 0.98))


def decay(r: Rating, periods: float = 1.0) -> Rating:
    """경기를 쉰 기간만큼 RD 를 키운다(확신도 감소)."""
    phi = math.sqrt(r.phi ** 2 + (r.vol ** 2) * max(periods, 0.0))
    return Rating(r.rating, min(phi * SCALE, DEFAULT_RD), r.vol)


def update(r: Rating, opponents: Sequence[tuple[Rating, float]], tau: float = TAU) -> Rating:
    """한 레이팅 기간의 결과들로 갱신. opponents = [(상대 레이팅, 결과 0~1), ...]"""
    if not opponents:
        return decay(r)

    mu, phi = r.mu, r.phi
    v_inv = 0.0
    delta_sum = 0.0
    for opp, s in opponents:
        gj = _g(opp.phi)
        Ej = _E(mu, opp.mu, opp.phi)
        v_inv += gj * gj * Ej * (1.0 - Ej)
        delta_sum += gj * (s - Ej)
    if v_inv <= 0:
        return decay(r)
    v = 1.0 / v_inv
    delta = v * delta_sum

    # 변동성 갱신 (Illinois 알고리즘)
    a = math.log(r.vol ** 2)

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta * delta - phi * phi - v - ex)
        den = 2.0 * (phi * phi + v + ex) ** 2
        return num / den - (x - a) / (tau * tau)

    A = a
    if delta * delta > phi * phi + v:
        B = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * tau) < 0 and k < 100:
            k += 1
        B = a - k * tau
    fA, fB = f(A), f(B)
    for _ in range(100):
        if abs(B - A) <= EPSILON:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA /= 2.0
        B, fB = C, fC
    new_vol = math.exp(A / 2.0)

    phi_star = math.sqrt(phi * phi + new_vol * new_vol)
    new_phi = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    new_mu = mu + new_phi * new_phi * delta_sum

    return Rating(
        rating=new_mu * SCALE + DEFAULT_RATING,
        rd=max(min(new_phi * SCALE, DEFAULT_RD), 30.0),
        vol=new_vol,
    )


def update_pair(
    a: Rating, b: Rating, a_games: int, b_games: int, a_won: bool, mov_weight: float = 0.25
) -> tuple[Rating, Rating]:
    """한 경기 결과로 양쪽을 동시에 갱신(서로의 갱신 전 값을 사용)."""
    sa = score_outcome(a_won, a_games, b_games, mov_weight)
    sb = score_outcome(not a_won, b_games, a_games, mov_weight)
    return update(a, [(b.copy(), sa)]), update(b, [(a.copy(), sb)])


# --- 표시용 레벨 -----------------------------------------------------------
def ntrp(rating: float) -> float:
    """레이팅 -> NTRP 유사 레벨. 1500 = 3.5, 175점 = 0.5 레벨."""
    level = 3.5 + (rating - DEFAULT_RATING) / 350.0
    return round(min(max(level, 1.0), 7.0) * 2) / 2


def level_label(r: Rating) -> str:
    lo, hi = r.interval95()
    if r.rd > 150:
        return f"NTRP {ntrp(r.rating):.1f} (측정 중)"
    return f"NTRP {ntrp(r.rating):.1f}"


def confidence_label(rd: float) -> str:
    if rd <= 60:
        return "확정"
    if rd <= 100:
        return "안정"
    if rd <= 180:
        return "측정 중"
    return "신규"


def competitiveness(a: Rating, b: Rating) -> float:
    """이 매치가 얼마나 팽팽한가 (0~1). 승률 예측이 50%에 가까울수록 1."""
    p = expected_score(a, b)
    return float(1.0 - 2.0 * abs(p - 0.5))


def predicted_score_line(a: Rating, b: Rating) -> str:
    p = expected_score(a, b)
    return f"예상 승률 {p * 100:.0f}% : {100 - p * 100:.0f}%"


__all__ = [
    "Rating", "DEFAULT_RATING", "DEFAULT_RD", "DEFAULT_VOL",
    "expected_score", "score_outcome", "update", "update_pair", "decay",
    "ntrp", "level_label", "confidence_label", "competitiveness", "predicted_score_line",
]
