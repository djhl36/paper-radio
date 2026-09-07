import React, { createContext, useContext, useEffect, useMemo, useReducer } from "react";
import { BUILTIN_ACTIVITIES } from "./engine/activities.js";
import { DEFAULT_PROFILE, applyLoad, contextMult, predict, recover, sleepRecover, clamp, r1 } from "./engine/model.js";
import { updateLearn, dateKey } from "./engine/learn.js";

const KEY = "energy-optimizer.v1";

export const initialData = {
  v: 1,
  profile: { ...DEFAULT_PROFILE },
  state: { hp: 75, mp: 75, debt: 0, ts: Date.now() },
  overrides: {},
  hidden: [],
  custom: [],
  learn: {},
  logs: [],
  plan: [],
  days: {},
  running: null
};

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return initialData;
    const parsed = JSON.parse(raw);
    return { ...initialData, ...parsed, profile: { ...DEFAULT_PROFILE, ...(parsed.profile || {}) } };
  } catch {
    return initialData;
  }
}

const uid = () => Math.random().toString(36).slice(2, 10);

function reducer(d, a) {
  switch (a.type) {
    case "replace":
      return { ...initialData, ...a.data, profile: { ...DEFAULT_PROFILE, ...(a.data.profile || {}) } };

    case "tick": {
      // 마지막 갱신 이후 흐른 시간만큼 자연 회복
      const hours = (a.now - (d.state.ts || a.now)) / 3600000;
      if (hours < 0.05 || d.running) return { ...d, state: { ...d.state, ts: a.now } };
      const s = recover(d.state, Math.min(hours, 16));
      return { ...d, state: { ...s, ts: a.now } };
    }

    case "setState":
      return { ...d, state: { ...d.state, hp: clamp(a.hp, 0, 100), mp: clamp(a.mp, 0, 100), ts: a.now } };

    case "profile":
      return { ...d, profile: { ...d.profile, ...a.patch } };

    case "checkin": {
      const s = sleepRecover(d.state, a.sleepHours, a.quality);
      const key = a.key;
      const hp = r1(a.hp ?? s.hp);
      const mp = r1(a.mp ?? s.mp);
      const day = {
        ...(d.days[key] || {}),
        sleepHours: a.sleepHours, quality: a.quality, flags: a.flags || [],
        hp, mp, checkedIn: true
      };
      return { ...d, state: { hp, mp, debt: s.debt, ts: a.now }, days: { ...d.days, [key]: day } };
    }

    case "flags": {
      const key = a.key;
      const day = { ...(d.days[key] || {}), flags: a.flags };
      return { ...d, days: { ...d.days, [key]: day } };
    }

    case "start":
      return { ...d, running: { id: uid(), actId: a.actId, startTs: a.now, durationMin: a.durationMin, intensity: a.intensity } };

    case "cancel":
      return { ...d, running: null };

    // 활동 완료(또는 과거 기록) → 상태 반영 + 개인계수 학습
    case "complete": {
      const { log } = a; // {actId, startTs, durationMin, intensity, pred, actual, output, note}
      const state = a.skipState ? d.state : { ...applyLoad(d.state, { ...log.actual, debt: log.pred.debt * (log.ratio?.hp ?? 1) }), ts: a.now };
      const learn = updateLearn(d.learn, log.actId, {
        rHp: log.ratio?.hp ?? 1,
        rMp: log.ratio?.mp ?? 1,
        predHp: log.pred.hp,
        predMp: log.pred.mp
      });
      return { ...d, running: null, state, learn, logs: [...d.logs, { id: uid(), ...log }] };
    }

    case "deleteLog":
      return { ...d, logs: d.logs.filter((l) => l.id !== a.id) };

    case "planAdd":
      return { ...d, plan: [...d.plan, { id: uid(), ...a.item }] };
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
      return { ...initialData, state: { ...initialData.state, ts: Date.now() } };

    default:
      return d;
  }
}

const Ctx = createContext(null);

export function AppProvider({ children }) {
  const [data, dispatch] = useReducer(reducer, undefined, load);

  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch { /* 용량 초과 등은 무시 */ }
  }, [data]);

  // 앱을 열 때 / 포커스가 돌아올 때 자연 회복 반영
  useEffect(() => {
    const tick = () => dispatch({ type: "tick", now: Date.now() });
    tick();
    const t = setInterval(tick, 60000);
    document.addEventListener("visibilitychange", tick);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", tick); };
  }, []);

  const value = useMemo(() => {
    const activities = [
      ...BUILTIN_ACTIVITIES.map((a) => (data.overrides[a.id] ? { ...a, ...data.overrides[a.id] } : a)),
      ...data.custom
    ].filter((a) => !data.hidden.includes(a.id));

    const today = dateKey(new Date());
    const day = data.days[today] || {};
    const ctx = {
      sleepTarget: data.profile.sleepTarget,
      sleepHours: day.sleepHours,
      flags: day.flags || []
    };
    const mult = contextMult(data.state, ctx);
    const actById = Object.fromEntries(activities.map((a) => [a.id, a]));

    const predictFor = (act, opt, state = data.state) =>
      predict(act, opt, state === data.state ? mult : contextMult(state, ctx), data.learn[act.id] || {});

    return { data, dispatch, activities, actById, ctx, mult, today, day, predictFor };
  }, [data]);

  return React.createElement(Ctx.Provider, { value }, children);
}

export const useApp = () => useContext(Ctx);
export { uid };
