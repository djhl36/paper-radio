// ── 하루를 블록으로 ─────────────────────────────────────────────────
// 기상~취침을 일정 간격(기본 30분)으로 잘라, 각 칸이 비었는지 / 무엇으로 찼는지 본다.
// 빈 칸은 "기록되지 않은 시간"이고, 이 앱에서는 그 자체가 정보다(어디로 샜는지).

export const SLOT_MIN = 30;

const floorTo = (ts, min) => Math.floor(ts / (min * 60000)) * (min * 60000);

/**
 * @param wakeTs/bedTs 하루의 범위
 * @param logs  [{id, actId, startTs, durationMin, ...}]
 * @param plan  [{id, actId, startTs, durationMin, ...}]
 * @param actById 활동 사전
 * @returns [{ start, end, log, plan, act, first, last, past }]
 */
export function buildBlocks({ wakeTs, bedTs, logs = [], plan = [], actById = {}, now = Date.now(), slotMin = SLOT_MIN }) {
  const from = floorTo(wakeTs, slotMin);
  const to = Math.max(from + slotMin * 60000, floorTo(bedTs + (slotMin * 60000 - 1), slotMin));
  const slots = [];

  const cover = (items) =>
    items
      .filter((x) => actById[x.actId])
      .map((x) => ({ ...x, act: actById[x.actId], end: x.startTs + (x.durationMin || 0) * 60000 }));

  const L = cover(logs);
  const P = cover(plan);

  for (let t = from; t < to; t += slotMin * 60000) {
    const end = t + slotMin * 60000;
    const mid = t + slotMin * 30000;
    const log = L.find((x) => x.startTs <= mid && x.end > mid);
    const pl = log ? null : P.find((x) => x.startTs <= mid && x.end > mid);
    const src = log || pl;
    slots.push({
      start: t,
      end,
      log: log || null,
      plan: pl || null,
      act: src?.act || null,
      id: src?.id || null,
      past: end <= now,
      now: t <= now && end > now
    });
  }

  // 같은 항목이 이어지는 구간의 처음/끝을 표시해 UI에서 한 덩어리로 그린다
  slots.forEach((s, i) => {
    s.first = !s.id || slots[i - 1]?.id !== s.id;
    s.last = !s.id || slots[i + 1]?.id !== s.id;
  });
  return slots;
}

/** 채워진 시간 / 빈 시간 요약 */
export function blockSummary(slots, slotMin = SLOT_MIN) {
  const past = slots.filter((s) => s.past);
  const filled = past.filter((s) => s.log).length;
  const planned = slots.filter((s) => !s.past && s.plan).length;
  return {
    filledMin: filled * slotMin,
    emptyMin: (past.length - filled) * slotMin,
    plannedMin: planned * slotMin,
    coverage: past.length ? Math.round((filled / past.length) * 100) : 0
  };
}
