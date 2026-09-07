import React, { useMemo, useState } from "react";
import { CATEGORIES } from "../engine/activities.js";
import { applyLoad } from "../engine/model.js";
import { useApp } from "../store.js";
import { CostText, Gauge, Sheet, durLabel } from "./ui.jsx";

const QUICK = [15, 30, 45, 60, 90, 120, 180];

/**
 * 활동 선택 → 시간·강도 조정 → 확인.
 * mode: "start"(지금 시작) | "log"(끝난 활동 기록) | "plan"(계획에 추가)
 */
export default function ActivityPicker({ open, onClose, mode = "start", onSubmit, defaultTime }) {
  const { activities, data, predictFor } = useApp();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [sel, setSel] = useState(null);
  const [dur, setDur] = useState(60);
  const [inten, setInten] = useState(5);
  const [time, setTime] = useState(defaultTime || "");

  const close = () => { setSel(null); setQ(""); onClose(); };

  const list = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return activities
      .filter((a) => (cat === "all" || a.cat === cat) && (!kw || a.name.toLowerCase().includes(kw)))
      .map((a) => ({ a, p: predictFor(a, { durationMin: a.dur, intensity: 5 }) }));
  }, [activities, cat, q, predictFor]);

  const pick = (a) => { setSel(a); setDur(a.dur); setInten(5); };

  const pred = sel ? predictFor(sel, { durationMin: dur, intensity: inten }) : null;
  const after = pred ? applyLoad(data.state, pred) : null;

  const submit = () => {
    let startTs = Date.now();
    if (mode === "plan" && time) {
      const [h, m] = time.split(":").map(Number);
      const d = new Date();
      d.setHours(h, m || 0, 0, 0);
      if (d.getTime() < Date.now() - 3600000) d.setDate(d.getDate() + 1);
      startTs = d.getTime();
    } else if (mode === "log") {
      startTs = Date.now() - dur * 60000;
    }
    onSubmit({ act: sel, durationMin: dur, intensity: inten, startTs });
    close();
  };

  const cta = mode === "plan" ? "계획에 추가" : mode === "log" ? "기록하고 반영" : "지금 시작";

  return (
    <Sheet open={open} onClose={close} title={sel ? `${sel.emoji} ${sel.name}` : "활동 선택"}>
      {!sel ? (
        <>
          <input type="text" placeholder="활동 검색" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="row wrap" style={{ gap: 6, margin: "10px 0 12px" }}>
            <button className={`chip sm ${cat === "all" ? "on" : ""}`} onClick={() => setCat("all")}>전체</button>
            {CATEGORIES.map((c) => (
              <button key={c.id} className={`chip sm ${cat === c.id ? "on" : ""}`} onClick={() => setCat(c.id)}>
                {c.emoji} {c.name}
              </button>
            ))}
          </div>
          <div className="list">
            {list.map(({ a, p }) => (
              <button className="item tap" key={a.id} onClick={() => pick(a)}>
                <span className="emoji">{a.emoji}</span>
                <span className="body">
                  <span className="t">{a.name}</span>
                  <span className="s">{durLabel(a.dur)} 기준</span>
                </span>
                <span className="cost"><CostText hp={p.hp} mp={p.mp} /></span>
              </button>
            ))}
            {!list.length ? <div className="empty">해당 활동이 없습니다. 활동 탭에서 새로 만들 수 있어요.</div> : null}
          </div>
        </>
      ) : (
        <>
          <label className="f">얼마나 {mode === "log" ? "했나요" : "할 건가요"}?</label>
          <div className="row wrap" style={{ gap: 6 }}>
            {QUICK.map((m) => (
              <button key={m} className={`chip sm ${dur === m ? "on" : ""}`} onClick={() => setDur(m)}>{durLabel(m)}</button>
            ))}
          </div>
          <input type="range" min="5" max="300" step="5" value={dur} onChange={(e) => setDur(+e.target.value)} style={{ marginTop: 8 }} />
          <div className="sub" style={{ textAlign: "center", marginTop: -4 }}>{durLabel(dur)}</div>

          <label className="f">강도 · 몰입도 <span className="dim">({inten}/10, 보통 5)</span></label>
          <input type="range" min="1" max="10" step="1" value={inten} onChange={(e) => setInten(+e.target.value)} />
          <div className="row between sub" style={{ marginTop: -4 }}>
            <span>가볍게</span><span>보통</span><span>최대</span>
          </div>

          {mode === "plan" ? (
            <>
              <label className="f">시작 시각</label>
              <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
            </>
          ) : null}

          <div className="card" style={{ marginTop: 16, marginBottom: 12 }}>
            <h2>예상 소모</h2>
            <div className="row between" style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 20, fontWeight: 700 }}><CostText hp={pred.hp} mp={pred.mp} /></div>
              {pred.debt > 1.5 ? <span className="badge yellow">회복비용 높음</span> : null}
            </div>
            <Gauge kind="hp" value={data.state.hp} ghost={after.hp} floor={data.profile.floor} label="HP" note={`→ ${Math.round(after.hp)}`} />
            <Gauge kind="mp" value={data.state.mp} ghost={after.mp} floor={data.profile.floor} label="MP" note={`→ ${Math.round(after.mp)}`} />
            {after.hp < data.profile.floor || after.mp < data.profile.floor ? (
              <div className="sub" style={{ marginTop: 10, color: "var(--warn)" }}>
                끝나고 나면 안전 예비분({data.profile.floor}) 아래로 내려갑니다.
              </div>
            ) : null}
          </div>

          <div className="grid2">
            <button className="btn" onClick={() => setSel(null)}>다른 활동</button>
            <button className="btn primary" onClick={submit}>{cta}</button>
          </div>
        </>
      )}
    </Sheet>
  );
}
