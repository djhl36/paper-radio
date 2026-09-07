// ── 개인 에너지 모델 ────────────────────────────────────────────────
// Load = 활동 기본치 × 시간 × 강도 × 지속시간 패널티 × 개인계수 × 컨텍스트
// 상태(HP/MP)는 0~100. 회복은 시간·수면·회복부채(debt)로 결정된다.

export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export const r1 = (v) => Math.round(v * 10) / 10;

export const FLAGS = [
  { id: "sick", emoji: "🤒", name: "몸이 안 좋음", hp: 1.35, mp: 1.2 },
  { id: "stress", emoji: "😖", name: "스트레스·시험기간", hp: 1.05, mp: 1.25 },
  { id: "busy", emoji: "🌀", name: "과부하 주간", hp: 1.1, mp: 1.15 },
  { id: "cycle", emoji: "🩸", name: "생리 주기", hp: 1.2, mp: 1.1 },
  { id: "peak", emoji: "✨", name: "컨디션 최고", hp: 0.85, mp: 0.85 }
];

export const DEFAULT_PROFILE = {
  sleepTarget: 7.5,
  floor: 20,        // 이 아래로 내려가면 위험 (안전 예비분)
  wakeHour: 7,
  bedHour: 23
};

/** 현재 상태·수면·플래그로부터 부하 배수를 계산 */
export function contextMult(state, ctx = {}) {
  const sleepTarget = ctx.sleepTarget ?? DEFAULT_PROFILE.sleepTarget;
  const slept = ctx.sleepHours ?? sleepTarget;
  const deficit = Math.max(0, sleepTarget - slept);
  const debt = state.debt || 0;

  let hp = (1 + 0.05 * deficit) * (1 + 0.35 * Math.max(0, (45 - state.hp) / 45)) * (1 + debt / 60);
  let mp = (1 + 0.09 * deficit) * (1 + 0.45 * Math.max(0, (45 - state.mp) / 45)) * (1 + debt / 80);

  for (const id of ctx.flags || []) {
    const f = FLAGS.find((x) => x.id === id);
    if (f) { hp *= f.hp; mp *= f.mp; }
  }
  // 지칠수록 회복형 활동의 효율은 올라간다
  const rest = 1 + 0.4 * (1 - (state.hp + state.mp) / 200);
  return { hp: clamp(hp, 0.6, 2.6), mp: clamp(mp, 0.6, 2.6), rest };
}

/** 활동 1회의 예상 부하 */
export function predict(act, { durationMin, intensity = 5 } = {}, mult = { hp: 1, mp: 1, rest: 1 }, learn = {}) {
  const h = Math.max(0, durationMin || 0) / 60;
  const fi = 0.55 + 0.09 * clamp(intensity, 1, 10);   // 강도 5 → 1.0
  const fm = 1 + (fi - 1) * 0.55;                     // 정신 부하는 강도 민감도가 낮다
  const dp = 1 + 0.15 * Math.max(0, h - 1.5);         // 오래 할수록 시간당 비용 상승
  const hRest = h <= 1 ? h : 1 + (h - 1) * 0.6;       // 회복은 길어질수록 체감 효율 감소
  const kHp = learn.kHp ?? 1;
  const kMp = learn.kMp ?? 1;

  const hp = act.hp >= 0
    ? act.hp * h * fi * dp * kHp * mult.hp
    : act.hp * hRest * kHp * (mult.rest ?? 1);
  const mp = act.mp >= 0
    ? act.mp * h * fm * dp * kMp * mult.mp
    : act.mp * hRest * kMp * (mult.rest ?? 1);

  const spent = Math.max(0, hp) * 0.6 + Math.max(0, mp) * 0.4;
  const debt = (act.rec || 0) * spent / 6;
  return { hp: r1(hp), mp: r1(mp), debt: r1(debt) };
}

/** 부하를 상태에 적용 */
export function applyLoad(state, load) {
  return {
    hp: clamp(state.hp - load.hp, 0, 100),
    mp: clamp(state.mp - load.mp, 0, 100),
    debt: Math.max(0, (state.debt || 0) + (load.debt || 0))
  };
}

/** 깨어 있는 동안의 자연 회복 (hours 시간 경과) */
export function recover(state, hours) {
  const h = Math.max(0, hours);
  const dq = 1 / (1 + (state.debt || 0) / 12);
  const hp = clamp(state.hp + 2.8 * h * (1 - state.hp / 100) * dq, 0, 100);
  const mp = clamp(state.mp + 2.4 * h * (1 - state.mp / 100) * dq, 0, 100);
  return { hp, mp, debt: (state.debt || 0) * Math.pow(0.5, h / 6) };
}

/** 수면 회복 */
export function sleepRecover(state, hours, quality = 0.8) {
  const q = clamp(quality, 0.2, 1);
  const eff = Math.min(1, Math.max(0, hours) / 8) * q;
  return {
    hp: clamp(state.hp + (100 - state.hp) * eff * 0.9, 0, 100),
    mp: clamp(state.mp + (100 - state.mp) * eff * 0.95, 0, 100),
    debt: Math.max(0, (state.debt || 0) * Math.max(0, 1 - Math.max(0, hours) / 9))
  };
}

/** 취침까지 남은 시간(h) */
export function hoursUntilBed(now, profile = DEFAULT_PROFILE) {
  const d = new Date(now);
  const bed = new Date(d);
  bed.setHours(profile.bedHour, 0, 0, 0);
  if (bed <= d) bed.setDate(bed.getDate() + 1);
  return Math.min(18, (bed - d) / 3600000);
}

/** 오늘 남은 "안전하게 쓸 수 있는" 예산 */
export function budget(state, profile = DEFAULT_PROFILE, now = Date.now()) {
  const hours = hoursUntilBed(now, profile);
  const rec = recover(state, hours);
  return {
    hours: r1(hours),
    hp: Math.max(0, r1(rec.hp - profile.floor)),
    mp: Math.max(0, r1(rec.mp - profile.floor))
  };
}

/**
 * 하루 시뮬레이션.
 * items: [{ act, durationMin, intensity, startTs }] (시간순 정렬 불필요)
 * 각 단계에서 상태가 변하므로 부하도 상태에 맞춰 다시 계산된다.
 */
export function simulate(state0, items, { now = Date.now(), profile = DEFAULT_PROFILE, ctx = {}, learn = {} } = {}) {
  const sorted = [...items].filter(Boolean).sort((a, b) => a.startTs - b.startTs);
  const bedTs = now + hoursUntilBed(now, profile) * 3600000;
  let state = { ...state0 };
  let t = now;
  let minHp = state.hp;
  let minMp = state.mp;
  const steps = [];

  for (const it of sorted) {
    const start = Math.max(t, it.startTs);
    if (start > t) state = recover(state, (start - t) / 3600000);
    t = start;
    const mult = contextMult(state, ctx);
    const load = predict(it.act, it, mult, learn[it.act.id] || {});
    const after = applyLoad(state, load);
    steps.push({ item: it, before: state, load, after, ts: t });
    state = after;
    t += (it.durationMin || 0) * 60000;
    minHp = Math.min(minHp, state.hp);
    minMp = Math.min(minMp, state.mp);
  }
  if (bedTs > t) state = recover(state, (bedTs - t) / 3600000);

  const total = steps.reduce(
    (a, s) => ({ hp: a.hp + s.load.hp, mp: a.mp + s.load.mp, min: a.min + (s.item.durationMin || 0) }),
    { hp: 0, mp: 0, min: 0 }
  );
  return {
    steps,
    end: { hp: r1(state.hp), mp: r1(state.mp), debt: r1(state.debt || 0) },
    min: { hp: r1(minHp), mp: r1(minMp) },
    total: { hp: r1(total.hp), mp: r1(total.mp), min: total.min }
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
export function suggestions(state0, items, opt, n = 2) {
  const base = simulate(state0, items, opt);
  const out = [];
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (!it.durationMin || it.durationMin < 45 || it.act.hp < 0) continue;
    const cut = Math.min(30, Math.round(it.durationMin / 2 / 5) * 5);
    const alt = items.map((x, j) => (j === i ? { ...x, durationMin: x.durationMin - cut } : x));
    const s = simulate(state0, alt, opt);
    const gain = { hp: r1(s.min.hp - base.min.hp), mp: r1(s.min.mp - base.min.mp) };
    const score = gain.hp * 0.5 + gain.mp * 0.5;
    if (score > 0.5) out.push({ item: it, cut, gain, score, end: s.end });
  }
  return out.sort((a, b) => b.score - a.score).slice(0, n);
}
