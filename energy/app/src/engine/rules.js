// ── 오늘의 규칙 ─────────────────────────────────────────────────────
// 사용자의 기록에서 반복 확인된 패턴과 본인이 세운 운영 원칙을 오늘 상황에 대입한다.
// 활동 분류는 이름 목록이 아니라 활동 자체의 성격(soc·rec)으로 판단한다.

import { bedBands, bedLabel, bedMinutes } from "./patterns.js";
import { r1 } from "./model.js";

const SOCIAL_AT = 6;   // 사회 부하 6 이상이면 "사람 쓰는 일"
const HEAVY_AT = 0.7;  // 회복 비용 0.7 이상이면 "여파가 남는 운동"
const LATE_BED = 25 * 60 + 30; // 01:30

const dayBefore = (key) => {
  const d = new Date(`${key}T00:00:00`);
  d.setDate(d.getDate() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

/**
 * @param rows       dayHistory() 결과 (통계용)
 * @param days       원본 days 객체
 * @param todayKey   오늘 날짜 키
 * @param planItems  오늘 남은 계획 [{act, durationMin, ...}]
 * @param recentActs 최근 7일 동안 실제로 한 활동(이름 배열)
 * @param nameToAct  활동 이름 → 활동 정의
 */
export function todayRules({ rows = [], days = {}, todayKey, planItems = [], recentActs = [], nameToAct = {}, state, profile, budget, simTotal }) {
  const out = [];
  const today = days[todayKey] || {};
  const prev = days[dayBefore(todayKey)] || {};

  // 1) 어젯밤 취침이 늦었는가
  const bed = bedMinutes(today) ?? bedMinutes(prev);
  if (bed != null && bed >= LATE_BED) {
    const bb = bedBands(rows);
    const late = bb[3];
    const early = bb[0];
    const detail =
      late?.n >= 5 && early?.n >= 4
        ? `기록상 2시 이후에 누운 날은 평균 ${late.sleep}시간을 자고 MP ${late.mp}, 24시 이전은 ${early.sleep}시간에 MP ${early.mp}였습니다.`
        : "늦게 누운 날은 기상 시각이 비슷해 수면량만 줄어듭니다.";
    out.push({ level: "warn", icon: "🌙", title: `${bedLabel(bed)}에 잠들었습니다`, detail });
  }

  // 2) 긴 낮잠 → 오늘 밤 취침 지연
  const nap = today.nap || 0;
  if (nap >= 2) {
    out.push({
      level: "warn", icon: "⏰", title: `오늘 ${nap}시간 낮잠`,
      detail: "이 패턴은 그날 밤 취침을 1시간 이상 미뤘습니다. 오후 늦게는 눕지 말고 가벼운 움직임으로 버티세요."
    });
  }

  // 3) 사회 부하가 겹치는가
  const socialToday = planItems.filter((p) => (p.act?.soc ?? 0) >= SOCIAL_AT);
  if (socialToday.length >= 2) {
    out.push({
      level: "warn", icon: "👥", title: `사람 쓰는 일이 ${socialToday.length}건 겹칩니다`,
      detail: `${socialToday.map((p) => p.act.name).join(" · ")} — 기록에서 사회활동이 겹친 날은 예상보다 10~20% 더 썼습니다. 하나를 다른 날로 옮기는 것이 가장 싼 조정입니다.`
    });
  }

  // 4) 고강도 운동 주 2회 상한
  const heavyRecent = recentActs.filter((n) => (nameToAct[n]?.rec ?? 0) >= HEAVY_AT).length;
  const heavyToday = planItems.filter((p) => (p.act?.rec ?? 0) >= HEAVY_AT).length;
  if (heavyRecent + heavyToday >= 3) {
    out.push({
      level: "warn", icon: "🎾", title: `최근 7일 고강도 운동 ${heavyRecent + heavyToday}회`,
      detail: "본인 기준은 주 2회입니다. 그 이상은 다음날 회복이 아니라 다다음날까지 밀렸습니다."
    });
  }

  // 5) 계획이 예산의 75%를 넘는가 (본인의 70~75% 원칙)
  if (simTotal && budget) {
    const cap = (budget.hp + budget.mp) * 0.75;
    const use = Math.max(0, simTotal.hp) + Math.max(0, simTotal.mp);
    if (cap > 0 && use > cap) {
      out.push({
        level: "warn", icon: "📊", title: `오늘 계획이 예산의 ${Math.round((use / (budget.hp + budget.mp)) * 100)}%입니다`,
        detail: "70~75%에서 멈추는 것이 당신이 지속 가능했던 지점입니다. 예비분을 남기세요."
      });
    } else if (cap > 0 && use > 0) {
      out.push({
        level: "good", icon: "✅", title: `계획은 예산의 ${Math.round((use / (budget.hp + budget.mp)) * 100)}%`,
        detail: "지속 가능한 구간입니다. 다 끝나도 추가로 붙이지 마세요 — Mission Complete."
      });
    }
  }

  // 6) 지금 MP가 먼저 마른 상태인가
  if (state && state.mp < state.hp - 10) {
    out.push({
      level: "info", icon: "🧠", title: "몸보다 머리가 먼저 비었습니다",
      detail: "당신에게 흔한 형태입니다. 운동은 가능하지만 사람·결정·새 입력은 오늘 줄이세요."
    });
  }

  // 7) 빈 날 경고
  if (!planItems.length && budget && budget.hours >= 5) {
    out.push({
      level: "info", icon: "🎣", title: "오늘은 계획이 비어 있습니다",
      detail: "기록상 빈 날이 오히려 무너지기 쉬웠습니다(유튜브 → 낮잠 → 취침 지연). 밖에 나가는 일 하나만 걸어 두면 나머지는 따라옵니다."
    });
  }

  return out;
}

/** days + logs에서 최근 n일 동안 실제로 한 활동 이름 */
export function recentActivityNames(days, logs, actById, todayKey, n = 7) {
  const from = new Date(`${todayKey}T00:00:00`);
  from.setDate(from.getDate() - n);
  const names = [];
  for (const [key, d] of Object.entries(days)) {
    const t = new Date(`${key}T00:00:00`);
    if (t >= from && key !== todayKey) names.push(...(d.did || d.activities || []));
  }
  for (const l of logs) {
    const t = new Date(l.startTs);
    if (t >= from) names.push(actById[l.actId]?.name || l.actId);
  }
  return names;
}

export const ruleSummary = (rules) => ({
  warn: rules.filter((r) => r.level === "warn").length,
  total: rules.length,
  worst: rules.some((r) => r.level === "warn") ? "warn" : rules.length ? "info" : "none"
});

export { r1 };
