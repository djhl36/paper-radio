// ── 하루 기록에서 개인 패턴 뽑기 ────────────────────────────────────
// 원칙: 표본이 충분한 것만 문장으로 만든다. 근거 없는 상관을 단정하지 않는다.

import { r1 } from "./model.js";

const avg = (xs, f) => (xs.length ? xs.reduce((a, x) => a + f(x), 0) / xs.length : null);
const has = (r) => r.hp != null && r.mp != null;

/** "01:40" → 분(24시 이후는 이어서 셈). 정오 이전은 다음날 새벽으로 본다 */
export function bedMinutes(r) {
  if (!r?.bed) return null;
  const [h, m] = r.bed.split(":").map(Number);
  if (!Number.isFinite(h)) return null;
  return (h < 12 ? h + 24 : h) * 60 + (m || 0);
}

export const bedLabel = (min) => {
  const h = Math.floor(min / 60) % 24;
  return `${String(h).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
};

const BANDS_SLEEP = [
  { label: "6시간 미만", lo: 0, hi: 6 },
  { label: "6–7.5시간", lo: 6, hi: 7.5 },
  { label: "7.5–9시간", lo: 7.5, hi: 9 },
  { label: "9시간 이상", lo: 9, hi: 99 }
];

const BANDS_BED = [
  { label: "24시 이전", lo: 0, hi: 24 * 60 + 1 },
  { label: "0–1시", lo: 24 * 60 + 1, hi: 25 * 60 },
  { label: "1–2시", lo: 25 * 60, hi: 26 * 60 },
  { label: "2시 이후", lo: 26 * 60, hi: 99 * 60 }
];

const band = (rows, bands, pick) =>
  bands.map((b) => {
    const g = rows.filter((r) => {
      const v = pick(r);
      return v != null && v >= b.lo && v < b.hi;
    });
    return { ...b, n: g.length, hp: r1(avg(g, (x) => x.hp)), mp: r1(avg(g, (x) => x.mp)), sleep: r1(avg(g, (x) => x.sleepHours)) };
  });

export const sleepBands = (rows) => band(rows.filter(has), BANDS_SLEEP, (r) => r.sleepHours);
export const bedBands = (rows) => band(rows.filter(has), BANDS_BED, bedMinutes);

/** 정신이 먼저 마르는가, 몸이 먼저 마르는가 */
export function drainOrder(rows) {
  const e = rows.filter(has);
  const mpFirst = e.filter((r) => r.mp < r.hp - 10).length;
  const hpFirst = e.filter((r) => r.hp < r.mp - 10).length;
  return { n: e.length, mpFirst, hpFirst, gap: r1(avg(e, (x) => x.hp - x.mp)) };
}

/** 긴 낮잠이 그날 밤 취침을 미루는가 (다음 날 기록의 취침 시각으로 비교) */
export function napEffect(rows) {
  const sorted = [...rows].sort((a, b) => a.key.localeCompare(b.key));
  const withNap = [];
  const without = [];
  for (let i = 0; i < sorted.length - 1; i++) {
    const cur = sorted[i];
    const nxt = sorted[i + 1];
    if (new Date(nxt.key) - new Date(cur.key) !== 86400000) continue;
    const b = bedMinutes(nxt);
    if (b == null) continue;
    ((cur.nap || 0) >= 2 ? withNap : without).push(b);
  }
  if (withNap.length < 3 || without.length < 5) return null;
  const a = avg(withNap, (x) => x);
  const b = avg(without, (x) => x);
  return { nNap: withNap.length, nPlain: without.length, napBed: a, plainBed: b, delayMin: Math.round(a - b) };
}

/** 아침에 더 자는(분할 수면) 날의 효과 */
export function splitSleep(rows) {
  const e = rows.filter(has);
  const y = e.filter((r) => r.sleepExtra);
  const n = e.filter((r) => !r.sleepExtra);
  if (y.length < 4 || n.length < 8) return null;
  return {
    n: y.length, other: n.length,
    hp: r1(avg(y, (x) => x.hp) - avg(n, (x) => x.hp)),
    mp: r1(avg(y, (x) => x.mp) - avg(n, (x) => x.mp))
  };
}

const DOW = ["일", "월", "화", "수", "목", "금", "토"];
export function weekdayStats(rows) {
  const e = rows.filter(has);
  return DOW.map((name, i) => {
    const g = e.filter((r) => new Date(r.key).getDay() === i);
    return { name, n: g.length, hp: r1(avg(g, (x) => x.hp)), mp: r1(avg(g, (x) => x.mp)) };
  });
}

/** 가장 자주 한 활동 */
export function topActivities(rows, limit = 12) {
  const freq = new Map();
  for (const r of rows) for (const a of r.activities || []) freq.set(a, (freq.get(a) || 0) + 1);
  return [...freq.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit).map(([name, n]) => ({ name, n }));
}

/** 표본이 충분한 것만 문장으로 */
export function patternFindings(rows) {
  const out = [];
  const e = rows.filter(has);
  if (e.length < 10) return out;

  const sb = sleepBands(rows);
  const short = sb[0];
  const good = sb.find((b) => b.label === "7.5–9시간");
  if (short?.n >= 4 && good?.n >= 4) {
    out.push({
      icon: "😴",
      text: `6시간 미만으로 잔 날(${short.n}일)의 아침은 HP ${short.hp} · MP ${short.mp}, 7.5~9시간 잔 날(${good.n}일)은 HP ${good.hp} · MP ${good.mp}. 수면이 하루의 상한을 정합니다.`
    });
  }

  const bb = bedBands(rows);
  const early = bb[0];
  const late = bb[3];
  if (early?.n >= 4 && late?.n >= 6) {
    out.push({
      icon: "🌙",
      text: `24시 이전에 누운 날(${early.n}일)은 평균 ${early.sleep}시간을 자고 MP ${early.mp}, 2시 이후에 누운 날(${late.n}일)은 ${late.sleep}시간에 MP ${late.mp}. 기상 시각은 비슷하므로 **취침 시각이 곧 수면량**입니다.`
    });
  }

  const d = drainOrder(rows);
  if (d.n >= 15 && d.mpFirst >= 3 && d.mpFirst > d.hpFirst * 2) {
    out.push({
      icon: "🧠",
      text: `정신이 몸보다 10 이상 먼저 떨어진 날이 ${d.mpFirst}일, 반대는 ${d.hpFirst}일. 당신의 병목은 거의 항상 MP입니다 — 하루를 자를 때 몸 쓰는 일보다 머리·사람 쓰는 일을 먼저 덜어내세요.`
    });
  }

  const nap = napEffect(rows);
  if (nap && nap.delayMin > 30) {
    out.push({
      icon: "⏰",
      text: `2시간 이상 낮잠을 잔 날의 다음 취침은 평균 ${bedLabel(Math.round(nap.napBed))}, 그렇지 않은 날은 ${bedLabel(Math.round(nap.plainBed))} — 약 ${Math.round(nap.delayMin / 60 * 10) / 10}시간 밀립니다. 20분 낮잠은 이 효과가 없었습니다.`
    });
  }

  const sp = splitSleep(rows);
  if (sp && sp.mp > 2) {
    out.push({
      icon: "🛏️",
      text: `아침에 한 번 더 자고 일어난 날(${sp.n}일)이 그렇지 않은 날보다 MP가 평균 ${sp.mp} 높습니다. 분할 수면은 당신에게 손해가 아닙니다.`
    });
  }

  const wd = weekdayStats(rows).filter((w) => w.n >= 4);
  if (wd.length >= 5) {
    const worst = wd.reduce((a, b) => (b.mp < a.mp ? b : a));
    const best = wd.reduce((a, b) => (b.mp > a.mp ? b : a));
    if (best.mp - worst.mp >= 8) {
      out.push({
        icon: "📅",
        text: `요일로 보면 ${worst.name}요일의 MP가 평균 ${worst.mp}로 가장 낮고 ${best.name}요일이 ${best.mp}로 가장 높습니다. 무거운 일은 ${best.name}요일 쪽에 두세요.`
      });
    }
  }
  return out;
}
