import { BUILTIN_ACTIVITIES } from "./activities.js";
import { updateLearn } from "./learn.js";
import { DEFAULT_PROFILE, contextMult, predict, r1 } from "./model.js";

const PATTERN = [
  { id: "deepwork", dur: [90, 120], hour: 9, out: [4, 5], bias: 1.0 },
  { id: "class", dur: [90], hour: 13, bias: 1.0 },
  { id: "paper", dur: [45, 60], hour: 15, out: [3, 4], bias: 1.15 },
  { id: "tennis", dur: [90, 120], hour: 18, bias: 1.4, days: [1, 3, 5] },
  { id: "friends", dur: [90, 120], hour: 19, bias: 1.2, days: [5, 6] },
  { id: "walk", dur: [25], hour: 12, bias: 1.0 },
  { id: "coding", dur: [60, 90, 150], hour: 21, out: [2, 3, 5], bias: 1.0, days: [0, 2, 4] }
];

const pick = (arr, i) => arr[i % arr.length];

/** 2주치 그럴듯한 기록을 만들어 학습·인사이트를 바로 확인할 수 있게 한다 */
export function makeDemo(now = Date.now()) {
  const logs = [];
  let learn = {};
  const state = { hp: 78, mp: 74, debt: 0 };

  for (let back = 13; back >= 0; back--) {
    const d = new Date(now - back * 86400000);
    const dow = d.getDay();
    let i = back;
    for (const p of PATTERN) {
      if (p.days && !p.days.includes(dow)) continue;
      const act = BUILTIN_ACTIVITIES.find((a) => a.id === p.id);
      if (!act) continue;
      const durationMin = pick(p.dur, i + dow);
      const intensity = 4 + ((i + dow) % 4);
      const start = new Date(d);
      start.setHours(p.hour, (i * 7) % 45, 0, 0);
      const mult = contextMult(state, { sleepTarget: DEFAULT_PROFILE.sleepTarget, flags: [] });
      const pred = predict(act, { durationMin, intensity }, mult, learn[act.id] || {});
      // 개인 편향 + 약간의 흔들림
      const jitter = 0.85 + (((i * 37 + dow * 11) % 30) / 100);
      const r = Math.max(0.5, Math.min(1.9, p.bias * jitter));
      const ratio = { hp: r, mp: Math.max(0.5, Math.min(1.9, r * 0.95)) };
      const actual = { hp: r1(pred.hp * ratio.hp), mp: r1(pred.mp * ratio.mp) };
      logs.push({
        id: `demo_${back}_${p.id}`,
        actId: act.id,
        startTs: start.getTime(),
        durationMin,
        intensity,
        pred,
        actual,
        ratio,
        output: p.out ? pick(p.out, i + dow) : null,
        note: null
      });
      learn = updateLearn(learn, act.id, { rHp: ratio.hp, rMp: ratio.mp, predHp: pred.hp, predMp: pred.mp });
      i++;
    }
  }
  return { logs, learn };
}
