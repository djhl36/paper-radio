// ── 일일 로그 텍스트 파서 ───────────────────────────────────────────
// 사용자가 원래 쓰던 양식을 그대로 읽는다. 여러 날을 한 번에 붙여넣어도 된다.
//
//   날짜: 7/31
//   수면: 1:40-7:30 +~11:40
//   신체 에너지: 50
//   정신 에너지: 60
//   오늘 할 일: real life rpg 작업
//   하면 좋은 일: 회복 스트레칭, 밴드 재활운동
//   특이사항: ...

import { dateKey } from "./learn.js";
import { FLAGS, r1 } from "./model.js";

const LABELS = [
  ["date", /^(날짜|일자|date)\s*[:：]/i],
  ["sleep", /^(수면|잠|sleep)\s*[:：]/i],
  ["hp", /^(신체\s*에너지|신체|physical|hp)\s*[:：]/i],
  ["mp", /^(정신\s*에너지|정신|mental|mp)\s*[:：]/i],
  ["must", /^(오늘\s*할\s*일|must[- ]?do|must|필수)\s*[:：]/i],
  ["nice", /^(하면\s*좋은\s*일|nice[- ]?to[- ]?do|nice|선택)\s*[:：]/i],
  ["note", /^(특이사항|관찰|메모|note|비고)\s*[:：]/i]
];

const labelOf = (line) => {
  for (const [key, re] of LABELS) if (re.test(line)) return key;
  return null;
};
const valueOf = (line) => line.slice(line.indexOf(":") >= 0 ? line.indexOf(":") + 1 : line.indexOf("：") + 1).trim();

/** "7/31" · "2026-07-31" · "7월 31일" → Date (미래로 60일 이상 벌어지면 작년으로 본다) */
export function parseDate(raw, today = new Date()) {
  const s = String(raw).trim();
  let y = null, m = null, d = null;
  let mt = s.match(/(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})/);
  if (mt) [, y, m, d] = mt.map(Number);
  else {
    mt = s.match(/(\d{1,2})\s*[-./월]\s*(\d{1,2})/);
    if (!mt) return null;
    [, m, d] = mt.map(Number);
    y = today.getFullYear();
  }
  if (!m || !d || m > 12 || d > 31) return null;
  const date = new Date(y, m - 1, d, 12, 0, 0, 0);
  if (!mt[1] || String(mt[1]).length < 4) {
    if (date - today > 60 * 86400000) date.setFullYear(y - 1);
  }
  return date;
}

const toMin = (h, m) => h * 60 + (m || 0);

/**
 * "1:40-7:30", "23:40~07:30", "1:40-7:30 +~11:40" (2차 수면), "약 7시간 50분", "7.5"
 * → { hours, note }
 */
export function parseSleep(raw) {
  const s = String(raw).trim();
  if (!s) return null;
  const ranges = [...s.matchAll(/(\d{1,2})\s*:\s*(\d{2})\s*[-~–]\s*(\d{1,2})\s*:\s*(\d{2})/g)];
  if (ranges.length) {
    let total = 0;
    for (const g of ranges) {
      const a = toMin(+g[1], +g[2]);
      const b = toMin(+g[3], +g[4]);
      total += b >= a ? b - a : b + 1440 - a;
    }
    // "+~11:40" 처럼 끝 시각만 적힌 2차 수면: 앞 구간의 종료 시각부터로 본다
    const tail = s.match(/\+\s*~?\s*(\d{1,2})\s*:\s*(\d{2})\s*$/);
    if (tail && ranges.length === 1) {
      const end = toMin(+ranges[0][3], +ranges[0][4]);
      const again = toMin(+tail[1], +tail[2]);
      if (again > end) total += again - end;
      return { hours: r1(total / 60), note: "2차 수면 포함" };
    }
    return { hours: r1(total / 60), note: ranges.length > 1 ? "분할 수면" : null };
  }
  const hm = s.match(/(\d{1,2})\s*시간\s*(\d{1,2})?\s*분?/);
  if (hm) return { hours: r1(+hm[1] + (+(hm[2] || 0)) / 60), note: null };
  const dec = s.match(/(\d{1,2}(?:\.\d)?)\s*h?/i);
  if (dec) return { hours: r1(+dec[1]), note: null };
  return null;
}

const splitItems = (s) =>
  String(s)
    .split(/[,·+/\n]|\s{2,}/)
    .map((x) => x.replace(/^[-•*\s]+/, "").trim())
    .filter(Boolean);

/** 특이사항에서 컨디션 플래그를 읽어낸다 */
function guessFlags(text) {
  const t = String(text || "");
  const out = [];
  if (/감기|아프|몸살|열이|컨디션 난조|아팠/.test(t)) out.push("sick");
  if (/스트레스|시험|마감|긴장|불안/.test(t)) out.push("stress");
  if (/과부하|무리|너무 많|빡셌|바쁨/.test(t)) out.push("busy");
  if (/컨디션 (좋|최고)|개운|가뿐/.test(t)) out.push("peak");
  return out.filter((f) => FLAGS.some((x) => x.id === f));
}

/**
 * 여러 날의 로그를 한 번에 파싱한다.
 * @returns {{ days: Object, entries: Array, skipped: number }}
 */
export function parseDailyLogs(text, today = new Date()) {
  const lines = String(text || "").split(/\r?\n/);
  const blocks = [];
  let cur = null;
  let field = null;

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { field = null; continue; }
    const key = labelOf(line);
    if (key === "date") {
      if (cur) blocks.push(cur);
      cur = { date: valueOf(line), sleep: "", hp: "", mp: "", must: [], nice: [], note: "" };
      field = null;
      continue;
    }
    if (!cur) continue;
    if (key) {
      field = key;
      const v = valueOf(line);
      if (key === "must" || key === "nice") { if (v) cur[key].push(...splitItems(v)); }
      else if (key === "note") cur.note += (cur.note ? " " : "") + v;
      else cur[key] = v;
      continue;
    }
    // 라벨 없는 줄은 직전 항목의 연속으로 본다
    if (field === "must" || field === "nice") cur[field].push(...splitItems(line));
    else if (field === "note") cur.note += " " + line;
  }
  if (cur) blocks.push(cur);

  const days = {};
  const entries = [];
  let skipped = 0;

  for (const b of blocks) {
    const date = parseDate(b.date, today);
    if (!date) { skipped++; continue; }
    const key = dateKey(date);
    const sleep = parseSleep(b.sleep);
    const hp = b.hp ? Number(String(b.hp).match(/\d+/)?.[0]) : null;
    const mp = b.mp ? Number(String(b.mp).match(/\d+/)?.[0]) : null;
    const entry = {
      flags: guessFlags(b.note),
      activities: [...b.must, ...b.nice],
      must: b.must,
      nice: b.nice,
      source: "daily-log"
    };
    if (sleep) {
      entry.sleepHours = sleep.hours;
      if (sleep.note) entry.sleepNote = sleep.note;
    }
    if (Number.isFinite(hp)) entry.hp = hp;
    if (Number.isFinite(mp)) entry.mp = mp;
    if (b.note.trim()) entry.note = b.note.trim();
    days[key] = entry;
    entries.push({ key, ...entry });
  }
  return { days, entries, skipped };
}
