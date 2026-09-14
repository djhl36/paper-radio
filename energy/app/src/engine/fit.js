// ── 기록으로 활동 파라미터 최적화 ────────────────────────────────────
// 개인계수(kHp/kMp)는 "예상 대비 몇 배"라는 하나의 숫자라서, 시간이나 강도에 따라
// 비용이 어떻게 달라지는지는 담지 못한다. 기록이 충분히 쌓이면 활동마다
//
//     시간당 비용 = a + b × (강도 − 5)
//
// 를 최소자승으로 직접 추정한다. a는 보통 강도에서의 시간당 비용, b는 강도 민감도다.
// 표본이 적을 때는 모델값(prior)쪽으로 끌어당겨(ridge) 튀지 않게 한다.

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const r1 = (v) => Math.round(v * 10) / 10;

export const MIN_FIT_SAMPLES = 6;
const PRIOR_WEIGHT = 6;      // 표본 n에 대해 prior 를 n/(n+6) 비율로 밀어낸다
const MIN_HOURS = 1 / 6;     // 10분 미만 기록은 시간당 환산이 불안정해 제외

/** [{x, y}] 에 대한 1차 최소자승. 분산이 없으면 기울기 0 */
function ols(points) {
  const n = points.length;
  if (!n) return null;
  const mx = points.reduce((a, p) => a + p.x, 0) / n;
  const my = points.reduce((a, p) => a + p.y, 0) / n;
  let sxx = 0;
  let sxy = 0;
  let syy = 0;
  for (const p of points) {
    sxx += (p.x - mx) ** 2;
    sxy += (p.x - mx) * (p.y - my);
    syy += (p.y - my) ** 2;
  }
  const slope = sxx > 1e-9 ? sxy / sxx : 0;
  const intercept = my - slope * mx;
  const r2 = syy > 1e-9 && sxx > 1e-9 ? clamp((sxy * sxy) / (sxx * syy), 0, 1) : 0;
  // x = 0 이 강도 5 이므로 intercept 가 "보통 강도에서의 시간당 비용"
  return { a: intercept, b: slope, r2, n, spread: Math.sqrt(sxx / n) };
}

/**
 * 활동 하나의 파라미터 추정.
 * @param logs   전체 기록
 * @param act    활동 정의 (prior 로 쓴다)
 */
export function fitActivity(logs, act) {
  const rows = logs.filter(
    (l) => l.actId === act.id && l.actual && (l.durationMin || 0) / 60 >= MIN_HOURS
  );
  if (rows.length < MIN_FIT_SAMPLES) return { n: rows.length, ok: false };

  const pts = rows.map((l) => {
    const hours = l.durationMin / 60;
    return {
      x: (l.intensity ?? 5) - 5,
      hp: l.actual.hp / hours,
      mp: l.actual.mp / hours
    };
  });
  const fHp = ols(pts.map((p) => ({ x: p.x, y: p.hp })));
  const fMp = ols(pts.map((p) => ({ x: p.x, y: p.mp })));
  if (!fHp || !fMp) return { n: rows.length, ok: false };

  const w = rows.length / (rows.length + PRIOR_WEIGHT);
  // 강도가 거의 안 변한 기록만 있으면 기울기는 신뢰할 수 없으므로 죽인다
  const slopeOk = fHp.spread >= 0.8;

  const blend = (fitted, prior) => r1(w * fitted + (1 - w) * prior);
  return {
    n: rows.length,
    ok: true,
    hp: blend(fHp.a, act.hp),
    mp: blend(fMp.a, act.mp),
    iHp: slopeOk ? r1(w * fHp.b) : 0,
    iMp: slopeOk ? r1(w * fMp.b) : 0,
    r2Hp: r1(fHp.r2 * 100) / 100,
    r2Mp: r1(fMp.r2 * 100) / 100,
    weight: r1(w * 100) / 100,
    spread: r1(fHp.spread),
    priorHp: act.hp,
    priorMp: act.mp
  };
}

/** 모든 활동에 대해 다시 맞춘다 (기록이 바뀔 때마다 호출) */
export function fitAll(logs, prev = {}, activities = null) {
  const byId = new Map();
  for (const l of logs) {
    if (!l.actual) continue;
    byId.set(l.actId, (byId.get(l.actId) || 0) + 1);
  }
  const out = {};
  for (const [actId, n] of byId) {
    if (n < MIN_FIT_SAMPLES) continue;
    const act = activities?.find((a) => a.id === actId) || prev[actId]?.act || { id: actId, hp: 0, mp: 0 };
    const f = fitActivity(logs, act);
    if (f.ok) out[actId] = f;
  }
  return out;
}

/** 활동 정의에 맞춰진 파라미터를 얹는다 */
export const withFit = (act, fit) =>
  fit?.ok ? { ...act, fitHp: fit.hp, fitMp: fit.mp, iHp: fit.iHp, iMp: fit.iMp, fitN: fit.n } : act;
