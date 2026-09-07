// ── 피드백 → 개인 계수 학습 ─────────────────────────────────────────
// 사용자는 "앱이 예상한 것보다 어땠는지"만 답한다. 예측에는 이미 개인계수가
// 들어 있으므로, 비율 r을 곱해 EMA로 갱신하면 자연스럽게 수렴한다.

import { clamp, r1 } from "./model.js";

export const FEEL_SCALE = [
  { r: 0.6, emoji: "😌", label: "가벼웠다" },
  { r: 1.0, emoji: "😐", label: "예상대로" },
  { r: 1.4, emoji: "😓", label: "힘들었다" },
  { r: 1.9, emoji: "🥵", label: "방전됐다" }
];

export const REST_SCALE = [
  { r: 0.5, emoji: "😑", label: "별로였다" },
  { r: 1.0, emoji: "🙂", label: "예상대로" },
  { r: 1.4, emoji: "😌", label: "잘 쉬었다" },
  { r: 1.8, emoji: "🤩", label: "완전 충전" }
];

const MIN_SIGNAL = 3; // 예측 절대값이 이보다 작으면 학습에 쓰지 않는다

export function updateLearn(learn, actId, { rHp = 1, rMp = 1, predHp = 0, predMp = 0 }) {
  const cur = learn[actId] || { kHp: 1, kMp: 1, n: 0 };
  const a = cur.n < 5 ? 0.3 : 0.18;
  const next = { ...cur, n: cur.n + 1 };
  if (Math.abs(predHp) >= MIN_SIGNAL) next.kHp = clamp(cur.kHp * (1 + a * (rHp - 1)), 0.4, 2.5);
  if (Math.abs(predMp) >= MIN_SIGNAL) next.kMp = clamp(cur.kMp * (1 + a * (rMp - 1)), 0.4, 2.5);
  next.kHp = Math.round(next.kHp * 1000) / 1000;
  next.kMp = Math.round(next.kMp * 1000) / 1000;
  return { ...learn, [actId]: next };
}

/** 활동별 누적 통계 */
export function activityStats(logs, activities, learn) {
  const byId = new Map();
  for (const log of logs) {
    if (!log.actual) continue;
    const s = byId.get(log.actId) || { n: 0, hours: 0, hp: 0, mp: 0, predHp: 0, predMp: 0, outputs: [] };
    s.n += 1;
    s.hours += (log.durationMin || 0) / 60;
    s.hp += log.actual.hp;
    s.mp += log.actual.mp;
    s.predHp += log.pred.hp;
    s.predMp += log.pred.mp;
    if (log.output) s.outputs.push({ min: log.durationMin, out: log.output, mp: log.actual.mp });
    byId.set(log.actId, s);
  }
  return activities
    .map((act) => {
      const s = byId.get(act.id);
      const k = learn[act.id] || { kHp: 1, kMp: 1, n: 0 };
      if (!s || s.hours <= 0) return { act, n: 0, k, hpPerH: act.hp, mpPerH: act.mp, bias: null };
      return {
        act,
        n: s.n,
        k,
        hours: r1(s.hours),
        hpPerH: r1(s.hp / s.hours),
        mpPerH: r1(s.mp / s.hours),
        bias: {
          hp: s.predHp !== 0 ? r1((s.hp / s.predHp - 1) * 100) : null,
          mp: s.predMp !== 0 ? r1((s.mp / s.predMp - 1) * 100) : null
        },
        outputs: s.outputs
      };
    })
    .sort((a, b) => b.n - a.n);
}

const BUCKETS = [
  { id: "<60", lo: 0, hi: 59, label: "60분 미만" },
  { id: "60-90", lo: 60, hi: 95, label: "60–90분" },
  { id: "90-120", lo: 96, hi: 125, label: "90–120분" },
  { id: ">120", lo: 126, hi: 1e9, label: "120분 초과" }
];

/** 산출물 기록이 있는 활동의 "최적 지속시간" 분석 */
export function bestDuration(logs, actId) {
  const rows = logs.filter((l) => l.actId === actId && l.output && l.actual);
  if (rows.length < 4) return null;
  const buckets = BUCKETS.map((b) => {
    const rs = rows.filter((l) => l.durationMin >= b.lo && l.durationMin <= b.hi);
    if (!rs.length) return { ...b, n: 0 };
    const out = rs.reduce((a, l) => a + l.output, 0) / rs.length;
    const cost = rs.reduce((a, l) => a + Math.max(1, l.actual.mp), 0) / rs.length;
    return { ...b, n: rs.length, out: r1(out), cost: r1(cost), eff: r1((out / cost) * 10) };
  }).filter((b) => b.n > 0);
  if (buckets.length < 2) return null;
  const best = buckets.reduce((a, b) => (b.eff > a.eff ? b : a));
  return { buckets, best };
}

/** 최근 n일 일별 소모량 */
export function dailyLoad(logs, days = 14) {
  const out = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today.getTime() - i * 86400000);
    const key = dateKey(d);
    const rows = logs.filter((l) => dateKey(new Date(l.startTs)) === key && l.actual);
    out.push({
      key,
      date: d,
      hp: r1(rows.reduce((a, l) => a + Math.max(0, l.actual.hp), 0)),
      mp: r1(rows.reduce((a, l) => a + Math.max(0, l.actual.mp), 0)),
      min: rows.reduce((a, l) => a + (l.durationMin || 0), 0)
    });
  }
  return out;
}

export const dateKey = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** 날짜별 기록(체크인·가져온 히스토리)을 시간순 배열로 */
export function dayHistory(days = {}) {
  return Object.entries(days)
    .map(([key, d]) => ({
      key,
      date: new Date(`${key}T00:00:00`),
      sleepHours: typeof d.sleepHours === "number" ? d.sleepHours : null,
      hp: typeof d.hp === "number" ? d.hp : null,
      mp: typeof d.mp === "number" ? d.mp : null,
      flags: d.flags || [],
      activities: d.activities || [],
      did: d.did || null,
      must: d.must || null,
      nice: d.nice || null,
      bed: d.bed || null,
      wake: d.wake || null,
      nap: d.nap || 0,
      sleepExtra: d.sleepExtra || 0,
      note: d.note || null,
      legacy: d.source === "legacy"
    }))
    .sort((a, b) => a.key.localeCompare(b.key));
}

