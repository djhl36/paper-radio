// ── Real Life RPG 에너지 엔진 이식 ───────────────────────────────────
// 원본: Documents/Real Life RPG/.../realtime/engine/
//   ResourceEngine.kt · SleepRecoveryCalculator.kt · WakePressureModel.kt
//   WorkoutLoadCalculator.kt · ContextLoadCalculator.kt · MetActivityCatalog.kt
//
// 원본은 웨어러블(심박·HRV·수면 세션)을 입력으로 받는다. 이 앱은 손으로 적는
// 기록이 입력이므로, 센서가 있던 자리에 같은 뜻의 수동 입력을 넣는다:
//   심박 예비율(HR reserve) → 사용자가 고른 강도 1~10
//   HRV(밤 회복 신호)      → 수면의 질 4단계
//   MET 카탈로그          → 활동의 신체 부하 phys(0~10)에서 환산
//   (원본에 없는) 영양     → 식사·수분 입력. 이 사람 기록에서 공복·혈당이 반복 변수라 추가
// 나머지 상수·곡선·가중치는 원본 값을 그대로 쓴다.

// model.js 와의 순환 참조를 피하려고 여기서 직접 둔다
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const r1 = (v) => Math.round(v * 10) / 10;

export const MS_HOUR = 3600000;

// ── 상수 (원본 그대로) ──────────────────────────────────────────────
const SLEEP_FLOOR = 0.62;
const MIN_RESTORATIVE_MIN = 240;
const SCORE_RANGE_MIN = 210;
const QUALITY_SENSITIVITY = 0.4;      // 원본 HRV_SENSITIVITY 자리
const DEBT_WINDOW_NIGHTS = 14;
const SLEEP_NEED_MIN = 420;
const DEBT_DECAY = 0.82;
const DEBT_PENALTY_PER_HOUR = 0.02;
const MAX_DEBT_PENALTY = 0.15;
const MIN_START_COEFFICIENT = 0.5;

const RISE_TAU_HOURS = 18.2;
const NAP_PRESSURE_CLEARANCE = 1.5;
const MP_WAKE_PRESSURE_WEIGHT = 0.5;
const HP_WAKE_PRESSURE_WEIGHT = 0.15;
const MP_FAST_FATIGUE_WEIGHT = 0.35;
const HP_ILLNESS_WEIGHT = 0.12;
const MP_ILLNESS_WEIGHT = 0.06;

const FAST_TAU_H = 3.0;
const STRUCTURAL_PEAK_H = 24.0;
const STRUCTURAL_DECAY_TAU_H = 36.0;

const MAX_BREAK_RECOVERY = 0.08;
const WALKING_HP_PER_HOUR = 0.025;
const STEP_HP_PER_1K = 0.004;   // 1000걸음당 HPmax 의 0.4% (10,000보 ≈ 4)

const RESTING_MET = 1.0;
const VIGOROUS_MET = 13.0;
const REFERENCE_MET = 7.5;
const MIN_MET_MULT = 0.45;
const MAX_MET_MULT = 1.7;
const HR_WEIGHT = 0.75;
const MET_WEIGHT = 0.25;
const SATURATION_K = 2.08;
const SIGNAL_QUALITY = 0.85;           // 심박 대신 자기보고 강도를 쓰므로 원본의 "HR 있으나 표본 부족" 등급

/** 알림도(circadian) 앵커: 기상 후 경과시간 → MPmax 대비 오프셋 */
const CIRCADIAN = [
  [0, -0.05], [1, 0], [3, 0.04], [5, 0.02], [7, -0.04],
  [9, 0], [11, 0.02], [13, 0], [16, -0.05], [18, -0.08]
];

// ── 수면 ────────────────────────────────────────────────────────────
/** 기상 시점에 탱크가 얼마나 찼는가 (0.62 ~ 1.0) */
export function sleepCoefficient(minutes, quality) {
  if (!minutes || minutes <= 0) return 1.0; // 데이터 없으면 중립 — 원본 규칙
  const durationScore = clamp((minutes - MIN_RESTORATIVE_MIN) / SCORE_RANGE_MIN, 0, 1);
  const base = SLEEP_FLOOR + (1 - SLEEP_FLOOR) * durationScore;
  // 원본의 HRV 보정 자리: 수면의 질(0.5~1.0)을 개인 평균 0.75 기준 편차로 환산
  const adj = quality == null ? 0 : clamp(((quality - 0.75) / 0.75) * QUALITY_SENSITIVITY, -0.08, 0.05);
  return clamp(base + adj, SLEEP_FLOOR, 1);
}

/** 최근 14박 수면부채 (어젯밤 제외). 최근일수록 가중치가 크다 */
export function sleepDebtPenalty(recentNightMinutes = []) {
  let weighted = 0;
  recentNightMinutes.slice(0, DEBT_WINDOW_NIGHTS).forEach((min, i) => {
    if (!min || min <= 0) return;
    weighted += Math.pow(DEBT_DECAY, i) * (Math.max(0, SLEEP_NEED_MIN - min) / 60);
  });
  return Math.min(weighted * DEBT_PENALTY_PER_HOUR, MAX_DEBT_PENALTY);
}

/** 항상성 수면압 (Process S) */
export const sleepPressure = (awakeHours) => 1 - Math.exp(-Math.max(0, awakeHours) / RISE_TAU_HOURS);

/** 일주기 알림도 (Process C) — 기상 시각 기준 보간 */
export function circadianModifier(hoursSinceWake) {
  const h = Math.max(0, hoursSinceWake);
  const last = CIRCADIAN[CIRCADIAN.length - 1];
  if (h >= last[0]) return last[1];
  const ui = CIRCADIAN.findIndex((p) => p[0] > h);
  if (ui <= 0) return CIRCADIAN[0][1];
  const [x0, y0] = CIRCADIAN[ui - 1];
  const [x1, y1] = CIRCADIAN[ui];
  return y0 + (y1 - y0) * ((h - x0) / (x1 - x0));
}

// ── 활동 → 운동 부하 ────────────────────────────────────────────────
/** MET 카탈로그 대신 활동의 신체 부하에서 환산 */
export const metOf = (act) => act.met ?? 1 + (act.phys ?? 3) * 0.9;

/** 원본 MetActivityProfile 의 활동별 파라미터를 phys·rec 에서 환산 */
export function profileOf(act) {
  const phys = act.phys ?? 3;
  return {
    met: metOf(act),
    modifier: act.loadModifier ?? clamp(0.5 + phys * 0.07, 0.4, 1.25),
    cap: act.loadCap ?? clamp(0.18 + phys * 0.05, 0.12, 0.75),
    fastShare: act.fastShare ?? clamp(0.35 + (act.rec ?? 0.3) * 0.35, 0.3, 0.72),
    refLoad: act.refLoad ?? clamp(0.6 + phys * 0.03, 0.55, 0.95)
  };
}

/** 강도 1~10 → 심박 예비율 자리 (0.15 ~ 0.90) */
export const intensityToHrRatio = (intensity) => clamp(0.15 + ((clamp(intensity, 1, 10) - 1) / 9) * 0.75, 0, 1);

/** 운동 세션 1회의 부하 → 즉시(fast)·지연(structural) 피로 */
export function workoutLoad(act, { durationMin = 60, intensity = 5 } = {}) {
  const p = profileOf(act);
  const hours = Math.max(0, durationMin) / 60;
  const hrRatio = intensityToHrRatio(intensity);
  const metIntensity = clamp((p.met - RESTING_MET) / (VIGOROUS_MET - RESTING_MET), 0, 1);
  const blended = hrRatio * HR_WEIGHT + metIntensity * MET_WEIGHT;
  const intensityWeight = (Math.exp(3 * blended) - 1) / (Math.exp(3) - 1);
  const metMultiplier = clamp(p.met / REFERENCE_MET, MIN_MET_MULT, MAX_MET_MULT);
  const sessionLoad = hours * intensityWeight * p.modifier * metMultiplier * SIGNAL_QUALITY;
  const depletion = clamp(p.cap * (1 - Math.exp(-SATURATION_K * sessionLoad / p.refLoad)), 0, p.cap);
  return { sessionLoad, depletion, fast: depletion * p.fastShare, slow: depletion * (1 - p.fastShare) };
}

/** 지연 근피로 곡선: 24시간에 정점, 이후 감쇠 (DOMS) */
export function structuralCurve(elapsedHours, recoveryMultiplier = 1) {
  const e = Math.max(0, elapsedHours);
  return e < STRUCTURAL_PEAK_H
    ? e / STRUCTURAL_PEAK_H
    : Math.exp(-(e - STRUCTURAL_PEAK_H) / (STRUCTURAL_DECAY_TAU_H / recoveryMultiplier));
}

export const fastDecay = (elapsedHours, recoveryMultiplier = 1) =>
  Math.exp(-Math.max(0, elapsedHours) / (FAST_TAU_H / recoveryMultiplier));

// ── 활동 → 인지·회복 부하 ───────────────────────────────────────────
/** 시간당 MP 추가 소모(MPmax 대비). 원본 ContextLoadCalculator 의 등급을 ment/soc/emo 로 환산 */
export function cognitivePerHour(act) {
  if (!act) return 0;
  const v = (act.ment ?? 0) * 0.0035 + (act.soc ?? 0) * 0.0015 + (act.emo ?? 0) * 0.0015;
  return clamp(v, 0, 0.05);
}

/** 휴식·식사의 부분 회복 (완전 회복은 수면에만) */
export function breakPerHour(act) {
  if (!act) return 0;
  if (act.id === "nap") return 0;               // 낮잠은 수면압 자체를 지운다
  if (act.cat === "recover" || act.hp < 0 || act.mp < 0) return 0.013;
  return 0;
}

export const isWorkout = (act) => (act?.phys ?? 0) >= 5;
export const isWalking = (act) => (act?.phys ?? 0) >= 2 && (act?.phys ?? 0) < 5 && act?.cat !== "work";

// ── 계획용 비용 (앞으로 이 활동을 하면 얼마나 드는가) ────────────────
/**
 * 원본은 "지금 상태"를 계산하는 엔진이라 앞으로의 비용이라는 개념이 없다.
 * 계획·추천에는 값이 필요하므로, 같은 공식에서 뽑은 즉시 피로(fast)를 HP 비용으로,
 * 인지 부하 누적을 MP 비용으로 환산한다. 지연 피로(slow)는 내일 몫으로 따로 돌려준다.
 */
export function activityCost(act, { durationMin = 60, intensity = 5 } = {}) {
  const hours = Math.max(0, durationMin) / 60;
  let hp = 0;
  let mp = 0;
  let fast = 0;
  let slow = 0;

  // 기록으로 맞춰진 파라미터가 있으면 모델 대신 그 값을 쓴다 (fit.js)
  if (act.fitHp != null) {
    const di = clamp(intensity, 1, 10) - 5;
    hp = (act.fitHp + (act.iHp || 0) * di) * hours;
    mp = (act.fitMp + (act.iMp || 0) * di) * hours;
    if (isWorkout(act) && hp > 0) {
      const w = workoutLoad(act, { durationMin, intensity });
      const scale = w.depletion > 1e-6 ? (hp / 100) / w.depletion : 0;
      fast = w.fast * scale;
      slow = w.slow * scale;
    }
    return { hp: r1(hp), mp: r1(mp), fast, slow, debt: r1(slow * 100) };
  }

  if (isWorkout(act)) {
    const w = workoutLoad(act, { durationMin, intensity });
    fast = w.fast;
    slow = w.slow;
    hp += w.fast * 100;
    mp += w.fast * MP_FAST_FATIGUE_WEIGHT * 100;
  } else if (isWalking(act)) {
    hp += hours * WALKING_HP_PER_HOUR * 100;
  }

  mp += hours * cognitivePerHour(act) * 100;
  const rest = hours * breakPerHour(act) * 100;
  mp -= rest;
  hp -= rest * 0.6;

  // 회복형 활동은 라이브러리에 적힌 음수 값을 그대로 존중한다 (낮잠·목욕 등)
  if (act.hp < 0) hp = act.hp * (hours <= 1 ? hours : 1 + (hours - 1) * 0.6);
  if (act.mp < 0) mp = act.mp * (hours <= 1 ? hours : 1 + (hours - 1) * 0.6);

  return { hp: r1(hp), mp: r1(mp), fast, slow, debt: r1(slow * 100) };
}

// ── 현재 상태 계산 ──────────────────────────────────────────────────
/**
 * 지금의 HP/MP를 "누적해서 깎아온 값"이 아니라 잠·시계·운동·인지부하에서 매번 다시 계산한다.
 * @param now        기준 시각(ms)
 * @param wakeTs     오늘 기상 시각(ms)
 * @param sleep      {minutes, quality}
 * @param nights     최근 14박 수면(분), 최신순, 어젯밤 제외
 * @param sessions   [{act, startTs, durationMin, intensity}] — 기상 이후의 활동
 * @param flags      컨디션 태그 id 배열
 * @param nutrition  0 부실 / 1 보통 / 2 충분 (null 이면 중립)
 * @param potential  {hp, mp} 상한 (기본 100)
 */
export function computeVitals({
  now = Date.now(), wakeTs, sleep = {}, nights = [], sessions = [],
  flags = [], nutrition = null, steps = null, bedTs = null,
  potential = { hp: 100, mp: 100 }
} = {}) {
  const hpMax = potential.hp ?? 100;
  const mpMax = potential.mp ?? 100;
  const wake = wakeTs ?? now;

  const base = sleepCoefficient(sleep.minutes, sleep.quality);
  const debt = sleepDebtPenalty(nights);
  const recovery = Math.max(MIN_START_COEFFICIENT, base - debt);

  const hoursSinceWake = Math.max(0, (now - wake) / MS_HOUR);

  // 활동 누적
  let cognitive = 0;
  let breaks = 0;
  let walking = 0;
  let napHours = 0;
  let fast = 0;
  let structural = 0;

  for (const s of sessions) {
    const start = Math.max(s.startTs, wake);
    const end = Math.min(s.startTs + (s.durationMin || 0) * 60000, now);
    if (end <= start) continue;
    const hours = (end - start) / MS_HOUR;
    const act = s.act;
    cognitive += hours * cognitivePerHour(act);
    breaks += hours * breakPerHour(act);
    if (isWalking(act)) walking += hours * WALKING_HP_PER_HOUR;
    if (act?.id === "nap" || act?.name === "낮잠") napHours += hours;
    if (isWorkout(act)) {
      const w = workoutLoad(act, { durationMin: s.durationMin, intensity: s.intensity ?? 5 });
      const elapsed = (now - end) / MS_HOUR;
      fast += w.fast * fastDecay(elapsed);
      structural += w.slow * structuralCurve(elapsed);
    }
  }
  // 워치가 준 걸음 수가 있으면 그쪽이 더 정확하므로 활동에서 추정한 걷기를 대체한다.
  // 하루 총량이므로 깨어 있는 시간에 비례해 지금까지 걸은 만큼만 센다.
  if (Number.isFinite(steps) && steps > 0) {
    const awakeSpan = bedTs && bedTs > wake ? (bedTs - wake) / MS_HOUR : 16;
    const done = clamp(hoursSinceWake / Math.max(1, awakeSpan), 0, 1);
    walking = (steps * done / 1000) * STEP_HP_PER_1K;
  }
  breaks = Math.min(breaks, MAX_BREAK_RECOVERY);
  fast = clamp(fast, 0, 1);
  structural = clamp(structural, 0, 1);

  const effectiveAwake = Math.max(0, hoursSinceWake - napHours * NAP_PRESSURE_CLEARANCE);
  const pressure = sleepPressure(effectiveAwake);
  const circ = circadianModifier(hoursSinceWake);

  // 컨디션 태그 → 원본의 illness/stress 신호 자리
  const illness = flags.includes("sick") ? 0.8 : flags.includes("cycle") ? 0.35 : 0;
  const stress = (flags.includes("stress") ? 1 : 0) + (flags.includes("busy") ? 0.6 : 0);
  const stressLoss = stress * mpMax * 0.015 * 2;
  const peak = flags.includes("peak") ? 0.05 : 0;

  // 영양 (원본에 없는 확장): 부실하면 깎고 충분하면 조금 돌려준다
  const nut = nutrition == null ? 0 : (nutrition - 1) * 0.04;

  const hpParts = [
    ["수면 기준 시작", hpMax * base],
    ["수면부채(14박)", -hpMax * (base - recovery)],
    ["깨어 있는 시간", -hpMax * pressure * HP_WAKE_PRESSURE_WEIGHT],
    ["운동 즉시 피로", -hpMax * fast],
    ["지연 근피로", -hpMax * structural],
    ["걷기·이동", -hpMax * walking],
    ["휴식·식사", hpMax * breaks * 0.6],
    ["영양", hpMax * nut],
    ["컨디션 난조", -hpMax * illness * HP_ILLNESS_WEIGHT],
    ["컨디션 최고", hpMax * peak]
  ];
  const mpParts = [
    ["수면 기준 시작", mpMax * base],
    ["수면부채(14박)", -mpMax * (base - recovery)],
    ["수면압(깨어 있는 시간)", -mpMax * pressure * MP_WAKE_PRESSURE_WEIGHT],
    ["일주기 리듬", mpMax * circ],
    ["인지·사회 부하", -mpMax * cognitive],
    ["휴식·낮잠", mpMax * breaks],
    ["운동 여파", -mpMax * fast * MP_FAST_FATIGUE_WEIGHT],
    ["영양", mpMax * nut * 0.75],
    ["스트레스", -stressLoss],
    ["컨디션 난조", -mpMax * illness * MP_ILLNESS_WEIGHT],
    ["컨디션 최고", mpMax * peak]
  ];

  const sum = (parts) => parts.reduce((a, [, v]) => a + v, 0);
  return {
    hp: clamp(sum(hpParts), 0, hpMax),
    mp: clamp(sum(mpParts), 0, mpMax),
    debt: r1(structural * 100),
    detail: {
      sleepCoefficient: r1(base * 100) / 100,
      sleepDebt: r1(debt * 100) / 100,
      recovery: r1(recovery * 100) / 100,
      hoursSinceWake: r1(hoursSinceWake),
      pressure: r1(pressure * 100) / 100,
      circadian: r1(circ * 100) / 100,
      fast: r1(fast * 100) / 100,
      structural: r1(structural * 100) / 100,
      napHours: r1(napHours)
    },
    hpParts: hpParts.filter(([, v]) => Math.abs(v) >= 0.5),
    mpParts: mpParts.filter(([, v]) => Math.abs(v) >= 0.5)
  };
}
