import React, { createContext, useContext, useEffect, useMemo, useReducer, useState } from "react";
import { BUILTIN_ACTIVITIES } from "./engine/activities.js";
import { DEFAULT_PROFILE, clamp, contextMult, predict, r1 } from "./engine/model.js";
import { computeVitals } from "./engine/rlr.js";
import { dateKey, rebuildLearn, updateLearn } from "./engine/learn.js";
import { fitAll, withFit } from "./engine/fit.js";

const KEY = "energy-optimizer.v1";

export const initialData = {
  v: 1,
  profile: { ...DEFAULT_PROFILE },
  overrides: {},
  hidden: [],
  custom: [],
  learn: {},
  logs: [],
  plan: [],
  days: {},
  running: null,
  override: null,     // 사용자가 직접 보정한 값 {hp, mp, key}
  calendar: { url: "", reminderMin: 30, notify: false, autoImport: false, lastSync: null },
  ai: { apiKey: "", model: "claude-opus-5" }
};

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return initialData;
    const parsed = JSON.parse(raw);
    return {
      ...initialData,
      ...parsed,
      profile: { ...DEFAULT_PROFILE, ...(parsed.profile || {}) },
      calendar: { ...initialData.calendar, ...(parsed.calendar || {}) },
      ai: { ...initialData.ai, ...(parsed.ai || {}) }
    };
  } catch {
    return initialData;
  }
}

const uid = () => Math.random().toString(36).slice(2, 10);

/** "07:30" → 그 날짜의 타임스탬프 */
export function timeOnDate(key, hhmm, fallbackHour = 8) {
  const d = new Date(`${key}T00:00:00`);
  if (hhmm && /^\d{1,2}:\d{2}$/.test(hhmm)) {
    const [h, m] = hhmm.split(":").map(Number);
    d.setHours(h, m, 0, 0);
  } else {
    d.setHours(fallbackHour, 0, 0, 0);
  }
  return d.getTime();
}

/** 취침~기상으로 수면 시간(분). 자정을 넘기면 이어서 센다 */
export function sleepMinutesFrom(bed, wake) {
  if (!bed || !wake) return null;
  const [bh, bm] = bed.split(":").map(Number);
  const [wh, wm] = wake.split(":").map(Number);
  if ([bh, bm, wh, wm].some((x) => !Number.isFinite(x))) return null;
  const a = bh * 60 + bm;
  const b = wh * 60 + wm;
  return b >= a ? b - a : b + 1440 - a;
}

function reducer(d, a) {
  switch (a.type) {
    case "replace":
      return {
        ...initialData,
        ...a.data,
        profile: { ...DEFAULT_PROFILE, ...(a.data.profile || {}) },
        calendar: { ...initialData.calendar, ...(a.data.calendar || {}) },
        ai: { ...initialData.ai, ...(a.data.ai || {}) }
      };

    case "profile":
      return { ...d, profile: { ...d.profile, ...a.patch } };

    case "calendar":
      return { ...d, calendar: { ...d.calendar, ...a.patch } };

    case "ai":
      return { ...d, ai: { ...d.ai, ...a.patch } };

    // 여러 날짜를 한 번에 병합 (삼성 헬스 가져오기 등)
    case "daysMerge": {
      const days = { ...d.days };
      for (const [k, patch] of Object.entries(a.patches)) days[k] = { ...(days[k] || {}), ...patch };
      return { ...d, days };
    }

    // 기록 여러 건 추가 (같은 시각·활동이면 중복으로 보고 건너뛴다)
    case "logsAdd": {
      const key = (l) => `${l.actId}@${Math.round(l.startTs / 60000)}`;
      const have = new Set(d.logs.map(key));
      const add = a.logs.filter((l) => !have.has(key(l))).map((l) => ({ id: uid(), ...l }));
      const logs = [...d.logs, ...add];
      return { ...d, logs, learn: rebuildLearn(logs) };
    }

    // 아침 체크인: 취침·기상 시각, 수면의 질, 영양, 컨디션 태그
    case "checkin": {
      const day = {
        ...(d.days[a.key] || {}),
        bed: a.bed, wake: a.wake,
        sleepHours: a.sleepMinutes != null ? r1(a.sleepMinutes / 60) : undefined,
        quality: a.quality,
        nutrition: a.nutrition,
        nap: a.nap ?? d.days[a.key]?.nap ?? 0,
        flags: a.flags || [],
        steps: a.steps ?? d.days[a.key]?.steps,
        meal: a.meal ?? d.days[a.key]?.meal ?? null,
        checkedIn: true
      };
      return { ...d, days: { ...d.days, [a.key]: day }, override: null };
    }

    case "dayPatch":
      return { ...d, days: { ...d.days, [a.key]: { ...(d.days[a.key] || {}), ...a.patch } } };

    // 직접 보정: 계산값과의 차이를 오늘 하루만 유지한다
    case "override":
      return { ...d, override: { hp: a.hp, mp: a.mp, baseHp: a.baseHp, baseMp: a.baseMp, key: a.key, ts: a.now } };
    case "clearOverride":
      return { ...d, override: null };

    case "start":
      return { ...d, running: { id: uid(), actId: a.actId, startTs: a.startTs ?? a.now, durationMin: a.durationMin, intensity: a.intensity } };
    case "cancel":
      return { ...d, running: null };

    case "complete": {
      const learn = updateLearn(d.learn, a.log.actId, {
        rHp: a.log.ratio?.hp ?? 1,
        rMp: a.log.ratio?.mp ?? 1,
        predHp: a.log.pred.hp,
        predMp: a.log.pred.mp
      });
      return { ...d, running: null, learn, logs: [...d.logs, { id: uid(), ...a.log }] };
    }

    case "updateLog": {
      const logs = d.logs.map((l) => (l.id === a.id ? { ...l, ...a.patch } : l));
      return { ...d, logs, learn: rebuildLearn(logs) };
    }

    case "deleteLog": {
      const logs = d.logs.filter((l) => l.id !== a.id);
      return { ...d, logs, learn: rebuildLearn(logs) };
    }

    case "planAdd":
      return { ...d, plan: [...d.plan, { id: uid(), ...a.item }] };
    case "planAddMany": {
      const have = new Set(d.plan.map((p) => p.uid).filter(Boolean));
      const add = a.items.filter((i) => !i.uid || !have.has(i.uid)).map((i) => ({ id: uid(), ...i }));
      return { ...d, plan: [...d.plan, ...add] };
    }
    case "planUpdate":
      return { ...d, plan: d.plan.map((p) => (p.id === a.id ? { ...p, ...a.patch } : p)) };
    case "planRemove":
      return { ...d, plan: d.plan.filter((p) => p.id !== a.id) };

    case "actUpsert": {
      const act = a.act;
      if (act.builtin) return { ...d, overrides: { ...d.overrides, [act.id]: act } };
      const exists = d.custom.some((c) => c.id === act.id);
      return { ...d, custom: exists ? d.custom.map((c) => (c.id === act.id ? act : c)) : [...d.custom, act] };
    }
    case "actHide":
      return { ...d, hidden: d.hidden.includes(a.id) ? d.hidden.filter((x) => x !== a.id) : [...d.hidden, a.id] };
    case "actDelete":
      return { ...d, custom: d.custom.filter((c) => c.id !== a.id) };
    case "actReset": {
      const o = { ...d.overrides };
      delete o[a.id];
      const learn = { ...d.learn };
      delete learn[a.id];
      return { ...d, overrides: o, learn };
    }

    case "reset":
      return { ...initialData };

    default:
      return d;
  }
}

const Ctx = createContext(null);

export function AppProvider({ children }) {
  const [data, dispatch] = useReducer(reducer, undefined, load);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch { /* 용량 초과 등은 무시 */ }
  }, [data]);

  useEffect(() => {
    const tick = () => setNow(Date.now());
    const t = setInterval(tick, 30000);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", tick); };
  }, []);

  const value = useMemo(() => {
    const baseActs = [
      ...BUILTIN_ACTIVITIES.map((a) => (data.overrides[a.id] ? { ...a, ...data.overrides[a.id] } : a)),
      ...data.custom
    ].filter((a) => !data.hidden.includes(a.id));
    // 기록이 충분히 쌓인 활동은 측정값으로 파라미터를 대체한다
    const fit = fitAll(data.logs, {}, baseActs);
    const activities = baseActs.map((a) => withFit(a, fit[a.id]));
    const actById = Object.fromEntries(activities.map((a) => [a.id, a]));

    const today = dateKey(new Date(now));
    const day = data.days[today] || {};

    // ── RLR 엔진 입력 만들기 ──
    const wakeTs = timeOnDate(today, day.wake, data.profile.wakeHour);
    const sleepMinutes = day.sleepHours != null ? day.sleepHours * 60 : null;
    const nights = Object.keys(data.days)
      .filter((k) => k < today)
      .sort((a, b) => b.localeCompare(a))
      .slice(0, 14)
      .map((k) => (data.days[k].sleepHours || 0) * 60);

    const sessions = data.logs
      .filter((l) => l.startTs + (l.durationMin || 0) * 60000 > wakeTs && actById[l.actId])
      .map((l) => ({ act: actById[l.actId], startTs: l.startTs, durationMin: l.durationMin, intensity: l.intensity }));
    if (data.running && actById[data.running.actId]) {
      sessions.push({
        act: actById[data.running.actId],
        startTs: data.running.startTs,
        durationMin: Math.max(1, (now - data.running.startTs) / 60000),
        intensity: data.running.intensity
      });
    }

    const bedTs = (() => {
      const h = data.profile.bedHour;
      const b = new Date(now);
      b.setHours(h, 0, 0, 0);
      if (b.getTime() <= wakeTs) b.setDate(b.getDate() + 1);
      return b.getTime();
    })();

    const vitalsCtx = {
      wakeTs,
      bedTs,
      steps: Number.isFinite(day.steps) ? day.steps : null,
      sleep: { minutes: sleepMinutes, quality: day.quality },
      nights,
      sessions,
      flags: day.flags || [],
      nutrition: day.nutrition ?? null,
      potential: { hp: 100, mp: 100 }
    };

    const computed = computeVitals({ ...vitalsCtx, now });
    const ov = data.override && data.override.key === today ? data.override : null;
    const offset = ov ? { hp: ov.hp - ov.baseHp, mp: ov.mp - ov.baseMp } : { hp: 0, mp: 0 };
    const state = {
      hp: clamp(computed.hp + offset.hp, 0, 100),
      mp: clamp(computed.mp + offset.mp, 0, 100),
      debt: computed.debt,
      ts: now
    };

    const ctx = { sleepTarget: data.profile.sleepTarget, sleepHours: day.sleepHours, flags: day.flags || [] };
    const mult = contextMult(state, ctx);

    const predictFor = (act, opt, st = state) =>
      predict(act, opt, st === state ? mult : contextMult(st, ctx), data.learn[act.id] || {});

    return {
      data, dispatch, now, activities, actById, ctx, mult, today, day,
      predictFor, vitalsCtx, vitals: computed, state, fit
    };
  }, [data, now]);

  return React.createElement(Ctx.Provider, { value }, children);
}

export const useApp = () => useContext(Ctx);
export { uid };
