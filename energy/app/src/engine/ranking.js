// ── 활동 정렬 ───────────────────────────────────────────────────────
// 최근에 했을수록, 자주 했을수록 위로. 앱에서 남긴 기록(logs)이 1순위지만,
// 가져온 하루 기록(days.activities)도 이름으로 같이 센다.

const DAY = 86400000;

export function activityScores(logs = [], days = {}, activities = [], now = Date.now()) {
  const byName = new Map(activities.map((a) => [a.name, a.id]));
  const score = new Map();
  const last = new Map();
  const count = new Map();

  const add = (id, ts, weight) => {
    if (!id) return;
    const ago = Math.max(0, (now - ts) / DAY);
    score.set(id, (score.get(id) || 0) + weight * Math.exp(-ago / 14));
    count.set(id, (count.get(id) || 0) + 1);
    if (!last.has(id) || ts > last.get(id)) last.set(id, ts);
  };

  for (const l of logs) add(l.actId, l.startTs, 1);
  for (const [key, d] of Object.entries(days)) {
    const ts = new Date(`${key}T12:00:00`).getTime();
    if (!Number.isFinite(ts)) continue;
    for (const name of d.did || d.activities || []) add(byName.get(name), ts, 0.6);
  }
  return { score, last, count };
}

/** 활동 목록을 최근·빈도 순으로 정렬 (동점은 원래 순서 유지) */
export function rankActivities(activities, ranking) {
  return [...activities]
    .map((a, i) => ({ a, i, s: ranking.score.get(a.id) || 0 }))
    .sort((x, y) => y.s - x.s || x.i - y.i)
    .map((x) => x.a);
}

export const usageLabel = (ranking, act, now = Date.now()) => {
  const n = ranking.count.get(act.id);
  if (!n) return null;
  const ago = Math.floor((now - (ranking.last.get(act.id) || now)) / DAY);
  return ago <= 0 ? "오늘" : ago === 1 ? "어제" : ago < 30 ? `${ago}일 전` : `${n}회`;
};
