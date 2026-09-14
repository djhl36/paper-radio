// ── 개인 에너지 모델 ────────────────────────────────────────────────
// 상태(HP/MP)는 "깎아온 누적값"이 아니라 Real Life RPG 엔진(rlr.js)으로
// 잠·시계·운동·인지부하·영양에서 매번 다시 계산한다.
// 이 파일은 그 위에 계획·판정·제안 같은 Energy Optimizer 고유 층을 올린다.

import { MS_HOUR, activityCost, computeVitals } from "./rlr.js";

export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export const r1 = (v) => Math.round(v * 10) / 10;

export const FLAGS = [
  { id: "sick", emoji: "🤒", name: "몸이 안 좋음", hp: 1.35, mp: 1.2 },
  { id: "stress", emoji: "😖", name: "스트레스·시험기간", hp: 1.05, mp: 1.25 },
  { id: "busy", emoji: "🌀", name: "과부하 주간", hp: 1.1, mp: 1.15 },
  { id: "cycle", emoji: "🩸", name: "생리 주기", hp: 1.2, mp: 1.1 },
  { id: "peak", emoji: "✨", name: "컨디션 최고", hp: 0.85, mp: 0.85 }
];

export const NUTRITION = [
  { v: 0, emoji: "🥲", label: "부실했다" },
  { v: 1, emoji: "🙂", label: "보통" },
  { v: 2, emoji: "😋", label: "잘 챙겼다" }
];

export const DEFAULT_PROFILE = {
  sleepTarget: 7.5,
  floor: 25,        // 이 아래로 내려가면 위험 (안전 예비분)
  wakeHour: 8,
  bedHour: 24
};

/** 지금 상태에서 활동이 얼마나 비싸질지 — 고갈될수록, 잠이 모자랄수록 비싸다 */
export function contextMult(state, ctx = {}) {
  const sleepTarget = ctx.sleepTarget ?? DEFAULT_PROFILE.sleepTarget;
  const slept = ctx.sleepHours ?? sleepTarget;
  const deficit = Math.max(0, sleepTarget - slept);

  let hp = (1 + 0.05 * deficit) * (1 + 0.35 * Math.max(0, (45 - state.hp) / 45));
  let mp = (1 + 0.09 * deficit) * (1 + 0.45 * Math.max(0, (45 - state.mp) / 45));

  for (const id of ctx.flags || []) {
    const f = FLAGS.find((x) => x.id === id);
    if (f) { hp *= f.hp; mp *= f.mp; }
  }
  const rest = 1 + 0.4 * (1 - (state.hp + state.mp) / 200);
  return { hp: clamp(hp, 0.6, 2.6), mp: clamp(mp, 0.6, 2.6), rest };
}

/** 활동 1회의 예상 부하 = RLR 비용 × 개인계수 × 상황 배수 */
export function predict(act, { durationMin, intensity = 5 } = {}, mult = { hp: 1, mp: 1, rest: 1 }, learn = {}) {
  const base = activityCost(act, { durationMin, intensity });
  const kHp = learn.kHp ?? 1;
  const kMp = learn.kMp ?? 1;
  const hp = base.hp >= 0 ? base.hp * kHp * mult.hp : base.hp * kHp * (mult.rest ?? 1);
  const mp = base.mp >= 0 ? base.mp * kMp * mult.mp : base.mp * kMp * (mult.rest ?? 1);
  return { hp: r1(hp), mp: r1(mp), debt: r1(base.debt * kHp), fast: base.fast, slow: base.slow };
}

/** 남은 계획 없이 시간만 흐를 때의 상태 */
export const stateAt = (ctx, ts, extraSessions = []) =>
  computeVitals({ ...ctx, now: ts, sessions: [...(ctx.sessions || []), ...extraSessions] });

/** 취침까지 남은 시간(h) */
export function hoursUntilBed(now, profile = DEFAULT_PROFILE) {
  const d = new Date(now);
  const bed = new Date(d);
  bed.setHours(profile.bedHour, 0, 0, 0);
  if (bed <= d) bed.setDate(bed.getDate() + 1);
  return Math.min(18, (bed - d) / MS_HOUR);
}

export const bedTimeOf = (now, profile) => now + hoursUntilBed(now, profile) * MS_HOUR;

/**
 * 오늘 남은 예산 = 아무것도 더 하지 않았을 때 취침 시점에 남아 있을 양에서 예비분을 뺀 것.
 * 시간이 흐르는 것만으로도 MP는 줄기 때문에, 이 값이 "지금부터 쓸 수 있는 양"이다.
 */
export function budget(ctx, profile = DEFAULT_PROFILE, now = Date.now()) {
  const hours = hoursUntilBed(now, profile);
  const atBed = stateAt(ctx, now + hours * MS_HOUR);
  return {
    hours: r1(hours),
    hp: Math.max(0, r1(atBed.hp - profile.floor)),
    mp: Math.max(0, r1(atBed.mp - profile.floor)),
    atBed
  };
}

/**
 * 하루 시뮬레이션. 각 시점의 상태를 RLR 엔진으로 다시 계산하므로
 * 활동 비용뿐 아니라 수면압·일주기 같은 "가만히 있어도 빠지는 몫"까지 포함된다.
 * items: [{ act, durationMin, intensity, startTs }]
 */
export function simulate(items, ctx, { now = Date.now(), profile = DEFAULT_PROFILE } = {}) {
  const sorted = [...items].filter(Boolean).sort((a, b) => a.startTs - b.startTs);
  const bedTs = bedTimeOf(now, profile);
  const start = stateAt(ctx, now);
  const planned = [];
  const steps = [];
  let minHp = start.hp;
  let minMp = start.mp;
  let t = now;

  for (const it of sorted) {
    const st = Math.max(t, it.startTs);
    const before = stateAt(ctx, st, planned);
    planned.push({ ...it, startTs: st });
    const end = st + (it.durationMin || 0) * 60000;
    const after = stateAt(ctx, end, planned);
    steps.push({ item: it, ts: st, before, after, load: { hp: r1(before.hp - after.hp), mp: r1(before.mp - after.mp) } });
    minHp = Math.min(minHp, after.hp);
    minMp = Math.min(minMp, after.mp);
    t = end;
  }

  const end = stateAt(ctx, bedTs, planned);
  const baseline = stateAt(ctx, bedTs);
  minHp = Math.min(minHp, end.hp);
  minMp = Math.min(minMp, end.mp);

  const minutes = sorted.reduce((a, x) => a + (x.durationMin || 0), 0);
  return {
    steps,
    start: { hp: r1(start.hp), mp: r1(start.mp) },
    end: { hp: r1(end.hp), mp: r1(end.mp), debt: r1(end.debt) },
    baseline: { hp: r1(baseline.hp), mp: r1(baseline.mp) },
    min: { hp: r1(minHp), mp: r1(minMp) },
    total: {
      hp: r1(start.hp - end.hp),
      mp: r1(start.mp - end.mp),
      min: minutes,
      // 계획 때문에 추가로 드는 몫 (시간이 흘러서 빠지는 몫을 뺀 값)
      planHp: r1(baseline.hp - end.hp),
      planMp: r1(baseline.mp - end.mp)
    }
  };
}

/** 시뮬레이션 결과 판정 */
export function verdict(sim, profile = DEFAULT_PROFILE) {
  const floor = profile.floor;
  const worst = Math.min(sim.min.hp, sim.min.mp);
  if (worst <= Math.max(6, floor - 12)) {
    return { level: "red", emoji: "🔴", title: "과부하 가능성이 높습니다", tone: "무너지기 전에 하나는 덜어내는 게 좋아요." };
  }
  if (worst < floor) {
    return { level: "yellow", emoji: "🟡", title: "빠듯한 하루입니다", tone: "예비분까지 끌어 쓰게 됩니다. 회복 시간을 끼워 넣으세요." };
  }
  return { level: "green", emoji: "🟢", title: "감당 가능한 하루입니다", tone: "예비분을 남기고 끝낼 수 있습니다." };
}

/** 계획을 줄였을 때의 개선폭 제안 (상위 n개) */
export function suggestions(items, ctx, opt, n = 2) {
  const base = simulate(items, ctx, opt);
  const out = [];
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (!it.durationMin || it.durationMin < 45 || (it.act?.hp ?? 0) < 0) continue;
    const cut = Math.min(30, Math.round(it.durationMin / 2 / 5) * 5);
    const alt = items.map((x, j) => (j === i ? { ...x, durationMin: x.durationMin - cut } : x));
    const s = simulate(alt, ctx, opt);
    const gain = { hp: r1(s.min.hp - base.min.hp), mp: r1(s.min.mp - base.min.mp) };
    const score = gain.hp * 0.5 + gain.mp * 0.5;
    if (score > 0.5) out.push({ item: it, cut, gain, score, end: s.end });
  }
  return out.sort((a, b) => b.score - a.score).slice(0, n);
}
