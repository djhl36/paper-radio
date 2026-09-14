import React, { useMemo, useState } from "react";
import { FLAGS, NUTRITION } from "../engine/model.js";
import { computeVitals } from "../engine/rlr.js";
import { sleepMinutesFrom, timeOnDate, useApp } from "../store.js";
import FoodPhoto from "./FoodPhoto.jsx";
import { Gauge, Sheet, durLabel } from "./ui.jsx";

const QUALITY = [
  { v: 0.5, label: "뒤척임" },
  { v: 0.7, label: "보통" },
  { v: 0.85, label: "좋음" },
  { v: 1, label: "푹 잠" }
];

const pad = (n) => String(n).padStart(2, "0");

export default function CheckinSheet({ open, onClose }) {
  const { data, dispatch, today, day, vitalsCtx, now } = useApp();
  const [bed, setBed] = useState(day.bed || `${pad(data.profile.bedHour % 24)}:00`);
  const [wake, setWake] = useState(day.wake || `${pad(data.profile.wakeHour)}:00`);
  const [quality, setQuality] = useState(day.quality ?? 0.7);
  const [nutrition, setNutrition] = useState(day.nutrition ?? 1);
  const [flags, setFlags] = useState(day.flags || []);
  const [nap, setNap] = useState(day.nap || 0);
  const [steps, setSteps] = useState(day.steps ?? "");
  const [meal, setMeal] = useState(day.meal || null);

  const minutes = sleepMinutesFrom(bed, wake);
  const toggle = (id) => setFlags((f) => (f.includes(id) ? f.filter((x) => x !== id) : [...f, id]));

  // 입력을 바꾸는 즉시 RLR 엔진으로 오늘 상태를 다시 계산해 보여준다
  const preview = useMemo(
    () =>
      computeVitals({
        ...vitalsCtx,
        now,
        wakeTs: timeOnDate(today, wake, data.profile.wakeHour),
        sleep: { minutes, quality },
        flags,
        nutrition,
        steps: steps === "" ? null : Number(steps)
      }),
    [minutes, quality, flags, nutrition, steps, wake, now, vitalsCtx]
  );

  const submit = () => {
    dispatch({
      type: "checkin", key: today, now: Date.now(),
      bed, wake, sleepMinutes: minutes, quality, nutrition, flags, nap,
      steps: steps === "" ? undefined : Number(steps),
      meal
    });
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title="☀️ 오늘 아침 체크인">
      <label className="f">언제 자고 언제 일어났나요?</label>
      <div className="grid2">
        <div>
          <div className="sub" style={{ marginBottom: 5 }}>취침</div>
          <input type="time" value={bed} onChange={(e) => setBed(e.target.value)} />
        </div>
        <div>
          <div className="sub" style={{ marginBottom: 5 }}>기상</div>
          <input type="time" value={wake} onChange={(e) => setWake(e.target.value)} />
        </div>
      </div>
      <div className="row between mt" style={{ fontSize: 13 }}>
        <span className="sub">잔 시간</span>
        <strong className="mono">{minutes != null ? durLabel(minutes) : "–"}</strong>
      </div>

      <label className="f">수면의 질</label>
      <div className="seg">
        {QUALITY.map((q) => (
          <button key={q.v} className={quality === q.v ? "on" : ""} onClick={() => setQuality(q.v)}>{q.label}</button>
        ))}
      </div>

      <label className="f">어제 걸음 수 <span className="dim">(워치가 있으면 설정에서 삼성 헬스 파일로 채울 수 있습니다)</span></label>
      <div className="row" style={{ gap: 8 }}>
        <input
          type="number" inputMode="numeric" min="0" max="80000" step="500" placeholder="예: 8000"
          value={steps} onChange={(e) => setSteps(e.target.value === "" ? "" : Math.max(0, +e.target.value))}
          style={{ flex: 1 }}
        />
        <span className="sub" style={{ whiteSpace: "nowrap" }}>걸음</span>
      </div>

      <label className="f">식사·수분은? <span className="dim">(공복·혈당이 컨디션을 자주 흔들었습니다)</span></label>
      <div className="seg">
        {NUTRITION.map((n) => (
          <button key={n.v} className={nutrition === n.v ? "on" : ""} onClick={() => setNutrition(n.v)}>
            {n.emoji} {n.label}
          </button>
        ))}
      </div>
      <div style={{ marginTop: 8 }}>
        <FoodPhoto
          onApply={(r) => {
            setNutrition(r.quality);
            setMeal({ items: r.items, kcal: r.kcal, protein: r.protein, note: r.note, at: r.at });
          }}
        />
      </div>
      {meal ? (
        <div className="sub" style={{ marginTop: 8 }}>
          기록됨: {meal.items?.join(", ") || "식사"}{meal.kcal ? ` · ${meal.kcal}kcal` : ""}{meal.protein ? ` · 단백질 ${meal.protein}g` : ""}
          <button className="chip sm" style={{ marginLeft: 8 }} onClick={() => setMeal(null)}>지우기</button>
        </div>
      ) : null}

      <label className="f">컨디션 태그 <span className="dim">(선택)</span></label>
      <div className="row wrap" style={{ gap: 6 }}>
        {FLAGS.map((f) => (
          <button key={f.id} className={`chip sm ${flags.includes(f.id) ? "on" : ""}`} onClick={() => toggle(f.id)}>
            {f.emoji} {f.name}
          </button>
        ))}
      </div>

      <label className="f">어제 낮잠 <span className="dim">({nap ? `${nap}시간` : "없음"})</span></label>
      <input type="range" min="0" max="4" step="0.5" value={nap} onChange={(e) => setNap(+e.target.value)} />

      <div className="card" style={{ marginTop: 16 }}>
        <h2>지금 상태 (계산값)</h2>
        <Gauge kind="hp" value={preview.hp} floor={data.profile.floor} label="HP · 몸" />
        <Gauge kind="mp" value={preview.mp} floor={data.profile.floor} label="MP · 머리" />
        <div className="sub mt">
          수면 계수 {Math.round(preview.detail.sleepCoefficient * 100)}% · 수면부채 −{Math.round(preview.detail.sleepDebt * 100)}%
          · 기상 후 {preview.detail.hoursSinceWake}시간
        </div>
      </div>

      <button className="btn primary block" onClick={submit}>시작하기</button>
    </Sheet>
  );
}
