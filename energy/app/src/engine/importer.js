// ── 외부 데이터 가져오기 ─────────────────────────────────────────────
// 이 앱이 내보낸 완전한 JSON뿐 아니라, 다른 곳에서 정리해 온 "느슨한" 기록도 받는다.
// 빠진 값은 엔진으로 다시 계산하고(예상 부하 → 체감 비율 → 개인계수), 모르는 활동은 만들어 준다.

import { BUILTIN_ACTIVITIES } from "./activities.js";
import { updateLearn } from "./learn.js";
import { clamp, predict, r1 } from "./model.js";

const NEUTRAL = { hp: 1, mp: 1, rest: 1 };

const pick = (o, keys) => {
  for (const k of keys) if (o?.[k] != null && o[k] !== "") return o[k];
  return undefined;
};

const num = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** 숫자 타임스탬프(초/밀리초), ISO, "2026-09-01 18:00", "2026/09/01" 모두 허용 */
export function parseTs(v) {
  if (v == null || v === "") return null;
  if (typeof v === "number") return v > 1e12 ? v : v * 1000;
  let s = String(v).trim().replace(/[./]/g, "-");
  if (!s.includes(":")) s += " 12:00"; // 시각이 없으면 정오로
  const t = Date.parse(s.replace(" ", "T"));
  return Number.isFinite(t) ? t : null;
}

const uid = () => Math.random().toString(36).slice(2, 10);

/**
 * @param raw  가져올 JSON (앱 내보내기 전체 또는 {logs:[...]} 같은 부분)
 * @param activities 현재 앱이 알고 있는 활동 목록 (이름 매칭용)
 * @param fallbackState 파일에 상태가 없을 때 유지할 현재 상태
 * @returns {{ data, report }}
 */
export function normalizeImport(raw, activities = [], fallbackState = null) {
  const report = { logs: 0, skipped: 0, created: [], plan: 0, days: 0, custom: 0 };
  if (!raw || typeof raw !== "object") throw new Error("JSON 객체가 아닙니다");

  const custom = Array.isArray(raw.custom) ? [...raw.custom] : [];
  const byId = new Map();
  const byName = new Map();
  for (const a of [...BUILTIN_ACTIVITIES, ...activities, ...custom]) {
    byId.set(a.id, a);
    byName.set(String(a.name).trim(), a);
  }

  // 활동 해석: id → 이름 → (없으면) 기록에서 추정해 새 활동 생성
  const resolve = (key, hint) => {
    const k = String(key ?? "").trim();
    if (!k) return null;
    if (byId.has(k)) return byId.get(k);
    if (byName.has(k)) return byName.get(k);
    const hours = Math.max(0.25, (hint?.durationMin || 60) / 60);
    const act = {
      id: `c_${uid()}`,
      emoji: hint?.emoji || "⭐",
      name: k,
      cat: hint?.cat || "life",
      hp: clamp(Math.round((hint?.hp ?? 0) / hours), -20, 20),
      mp: clamp(Math.round((hint?.mp ?? 0) / hours), -20, 20),
      phys: 3, ment: 3, soc: 2, emo: 2,
      rec: 0.3,
      dur: Math.round((hint?.durationMin || 60) / 5) * 5,
      out: false,
      builtin: false
    };
    custom.push(act);
    byId.set(act.id, act);
    byName.set(act.name, act);
    report.created.push(act.name);
    return act;
  };

  // ── 기록 ──
  const rawLogs = Array.isArray(raw.logs) ? raw.logs : Array.isArray(raw) ? raw : [];
  const parsed = [];
  for (const l of rawLogs) {
    const startTs = parseTs(pick(l, ["startTs", "start", "date", "날짜", "일시", "when"]));
    const durationMin = num(pick(l, ["durationMin", "minutes", "min", "duration", "분", "시간(분)"]));
    const hp = num(pick(l, ["hp", "HP", "actualHp"])) ?? num(l.actual?.hp);
    const mp = num(pick(l, ["mp", "MP", "actualMp"])) ?? num(l.actual?.mp);
    const name = pick(l, ["actId", "activity", "act", "name", "활동"]);
    if (!startTs || !durationMin || durationMin <= 0 || !name) { report.skipped++; continue; }

    const act = resolve(name, { durationMin, hp: hp ?? 0, mp: mp ?? 0 });
    if (!act) { report.skipped++; continue; }
    parsed.push({
      actId: act.id,
      act,
      startTs,
      durationMin,
      intensity: clamp(num(pick(l, ["intensity", "강도"])) ?? 5, 1, 10),
      actualIn: hp == null && mp == null ? null : { hp: hp ?? 0, mp: mp ?? 0 },
      predIn: l.pred && num(l.pred.hp) != null ? l.pred : null,
      ratioIn: l.ratio || null,
      output: num(pick(l, ["output", "성과"])),
      note: pick(l, ["note", "메모"]) ?? null
    });
  }
  parsed.sort((a, b) => a.startTs - b.startTs);

  // 시간순으로 훑으며 예상 부하 → 체감 비율 → 개인계수를 다시 만든다
  let learn = {};
  const logs = [];
  for (const p of parsed) {
    const pred = p.predIn
      ? { hp: num(p.predIn.hp) ?? 0, mp: num(p.predIn.mp) ?? 0, debt: num(p.predIn.debt) ?? 0 }
      : predict(p.act, { durationMin: p.durationMin, intensity: p.intensity }, NEUTRAL, learn[p.actId] || {});
    const actual = p.actualIn ? { hp: r1(p.actualIn.hp), mp: r1(p.actualIn.mp) } : { hp: pred.hp, mp: pred.mp };
    const ratio = p.ratioIn
      ? { hp: num(p.ratioIn.hp) ?? 1, mp: num(p.ratioIn.mp) ?? 1 }
      : {
          hp: Math.abs(pred.hp) >= 1 ? clamp(actual.hp / pred.hp, 0.3, 2.5) : 1,
          mp: Math.abs(pred.mp) >= 1 ? clamp(actual.mp / pred.mp, 0.3, 2.5) : 1
        };
    learn = updateLearn(learn, p.actId, { rHp: ratio.hp, rMp: ratio.mp, predHp: pred.hp, predMp: pred.mp });
    logs.push({
      id: `i_${uid()}`,
      actId: p.actId,
      startTs: p.startTs,
      durationMin: p.durationMin,
      intensity: p.intensity,
      pred,
      actual,
      ratio,
      output: p.output != null ? clamp(p.output, 1, 5) : null,
      note: p.note
    });
    report.logs++;
  }

  // ── 계획 ──
  const plan = [];
  for (const p of Array.isArray(raw.plan) ? raw.plan : []) {
    const startTs = parseTs(pick(p, ["startTs", "start", "date", "시각"]));
    const durationMin = num(pick(p, ["durationMin", "minutes", "min", "분"]));
    const act = resolve(pick(p, ["actId", "activity", "act", "name", "활동"]), { durationMin: durationMin || 60 });
    if (!startTs || !durationMin || !act) continue;
    plan.push({ id: `i_${uid()}`, actId: act.id, startTs, durationMin, intensity: clamp(num(p.intensity) ?? 5, 1, 10) });
    report.plan++;
  }

  const days = raw.days && typeof raw.days === "object" ? raw.days : {};
  report.days = Object.keys(days).length;
  report.custom = custom.length;

  const out = {
      ...raw,
      v: 1,
      custom,
      hidden: Array.isArray(raw.hidden) ? raw.hidden : [],
      overrides: raw.overrides && typeof raw.overrides === "object" ? raw.overrides : {},
      learn: Object.keys(learn).length ? learn : raw.learn || {},
      logs,
      plan,
      days,
      running: null
  };
  // undefined를 넘기면 기본값을 덮어써 버리므로, 있는 것만 남긴다
  const state = raw.state || fallbackState;
  if (state) out.state = state; else delete out.state;
  if (raw.profile) out.profile = raw.profile; else delete out.profile;

  return { data: out, report };
}
