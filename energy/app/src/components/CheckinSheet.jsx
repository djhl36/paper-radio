import React, { useState } from "react";
import { FLAGS, sleepRecover } from "../engine/model.js";
import { useApp } from "../store.js";
import { Gauge, Sheet } from "./ui.jsx";

const QUALITY = [
  { v: 0.5, label: "뒤척임" },
  { v: 0.7, label: "보통" },
  { v: 0.85, label: "좋음" },
  { v: 1, label: "푹 잠" }
];

export default function CheckinSheet({ open, onClose }) {
  const { data, dispatch, today, day } = useApp();
  const [hours, setHours] = useState(day.sleepHours ?? data.profile.sleepTarget);
  const [quality, setQuality] = useState(day.quality ?? 0.7);
  const [flags, setFlags] = useState(day.flags || []);
  const [manual, setManual] = useState(false);
  const est = sleepRecover(data.state, hours, quality);
  const [hp, setHp] = useState(Math.round(est.hp));
  const [mp, setMp] = useState(Math.round(est.mp));

  const toggle = (id) => setFlags((f) => (f.includes(id) ? f.filter((x) => x !== id) : [...f, id]));

  const submit = () => {
    dispatch({
      type: "checkin",
      key: today,
      now: Date.now(),
      sleepHours: hours,
      quality,
      flags,
      hp: manual ? hp : undefined,
      mp: manual ? mp : undefined
    });
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title="☀️ 오늘 아침 체크인">
      <label className="f">몇 시간 잤나요? <span className="dim">({hours}시간)</span></label>
      <input type="range" min="3" max="11" step="0.5" value={hours} onChange={(e) => setHours(+e.target.value)} />

      <label className="f">수면의 질</label>
      <div className="seg">
        {QUALITY.map((q) => (
          <button key={q.v} className={quality === q.v ? "on" : ""} onClick={() => setQuality(q.v)}>{q.label}</button>
        ))}
      </div>

      <label className="f">오늘의 컨디션 태그 <span className="dim">(선택 — 부하 계산에 반영됩니다)</span></label>
      <div className="row wrap" style={{ gap: 6 }}>
        {FLAGS.map((f) => (
          <button key={f.id} className={`chip sm ${flags.includes(f.id) ? "on" : ""}`} onClick={() => toggle(f.id)}>
            {f.emoji} {f.name}
          </button>
        ))}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="row between" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>오늘의 시작 상태</h2>
          <button className="chip sm" onClick={() => { setManual(!manual); setHp(Math.round(est.hp)); setMp(Math.round(est.mp)); }}>
            {manual ? "자동 계산" : "직접 맞추기"}
          </button>
        </div>
        <Gauge kind="hp" value={manual ? hp : est.hp} floor={data.profile.floor} label="HP" />
        {manual ? <input type="range" min="0" max="100" value={hp} onChange={(e) => setHp(+e.target.value)} /> : null}
        <Gauge kind="mp" value={manual ? mp : est.mp} floor={data.profile.floor} label="MP" />
        {manual ? <input type="range" min="0" max="100" value={mp} onChange={(e) => setMp(+e.target.value)} /> : null}
      </div>

      <button className="btn primary block" onClick={submit}>시작하기</button>
    </Sheet>
  );
}
