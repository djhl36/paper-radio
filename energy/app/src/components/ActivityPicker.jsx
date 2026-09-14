import React, { useMemo, useState } from "react";
import { CATEGORIES } from "../engine/activities.js";
import { activityScores, rankActivities, usageLabel } from "../engine/ranking.js";
import { useApp } from "../store.js";
import { CostText, DurationField, Gauge, Sheet, WhenField, durLabel } from "./ui.jsx";


/**
 * 활동 선택 → 시간·강도 조정 → 확인.
 * mode: "start"(지금 시작) | "log"(끝난 활동 기록) | "plan"(계획에 추가)
 */
export default function ActivityPicker({ open, onClose, mode = "start", onSubmit, defaultTime, presetStart = null, presetDuration = null }) {
  const { activities, data, state, predictFor, now } = useApp();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("all");
  const [sel, setSel] = useState(null);
  const [dur, setDur] = useState(60);
  const [inten, setInten] = useState(5);
  const [startTs, setStartTs] = useState(now);

  const close = () => { setSel(null); setQ(""); onClose(); };

  const ranking = useMemo(() => activityScores(data.logs, data.days, activities, now), [data.logs, data.days, activities]);

  const list = useMemo(() => {
    const kw = q.trim().toLowerCase();
    const filtered = activities.filter((a) => (cat === "all" || a.cat === cat) && (!kw || a.name.toLowerCase().includes(kw)));
    return rankActivities(filtered, ranking).map((a) => ({
      a,
      p: predictFor(a, { durationMin: a.dur, intensity: 5 }),
      used: usageLabel(ranking, a, now)
    }));
  }, [activities, cat, q, ranking, predictFor]);

  const pick = (a) => {
    setSel(a);
    setDur(presetDuration || a.dur);
    setInten(5);
    if (presetStart) setStartTs(presetStart);
    else if (mode === "log") setStartTs(now - a.dur * 60000);
    else if (mode === "plan") {
      const d = new Date(now);
      if (defaultTime) {
        const [h, m] = defaultTime.split(":").map(Number);
        d.setHours(h || 0, m || 0, 0, 0);
      } else {
        d.setHours(d.getHours() + 1, 0, 0, 0);
      }
      setStartTs(d.getTime());
    } else setStartTs(now);
  };

  const pred = sel ? predictFor(sel, { durationMin: dur, intensity: inten }) : null;
  const after = pred ? { hp: Math.max(0, state.hp - pred.hp), mp: Math.max(0, state.mp - pred.mp) } : null;

  const submit = () => {
    onSubmit({ act: sel, durationMin: dur, intensity: inten, startTs });
    close();
  };

  const cta = mode === "plan" ? "계획에 추가" : mode === "log" ? "기록하고 반영" : "시작";
  const timeLabel = mode === "plan" ? "시작 시각" : mode === "log" ? "언제 했나요?" : "시작 시각";

  return (
    <Sheet open={open} onClose={close} title={sel ? `${sel.emoji} ${sel.name}` : "활동 선택"}>
      {!sel ? (
        <>
          <input type="text" placeholder="활동 검색" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="row wrap" style={{ gap: 6, margin: "10px 0 12px" }}>
            <button className={`chip sm ${cat === "all" ? "on" : ""}`} onClick={() => setCat("all")}>최근·자주</button>
            {CATEGORIES.map((c) => (
              <button key={c.id} className={`chip sm ${cat === c.id ? "on" : ""}`} onClick={() => setCat(c.id)}>
                {c.emoji} {c.name}
              </button>
            ))}
          </div>
          <div className="list">
            {list.map(({ a, p, used }) => (
              <button className="item tap" key={a.id} onClick={() => pick(a)}>
                <span className="emoji">{a.emoji}</span>
                <span className="body">
                  <span className="t">
                    {a.name}
                    {a.fitHp != null ? <span className="badge green" style={{ marginLeft: 6, fontSize: 10 }}>측정됨</span> : null}
                  </span>
                  <span className="s">{durLabel(a.dur)} 기준{used ? ` · ${used}` : ""}</span>
                </span>
                <span className="cost"><CostText hp={p.hp} mp={p.mp} /></span>
              </button>
            ))}
            {!list.length ? <div className="empty">해당 활동이 없습니다. 활동 탭에서 새로 만들 수 있어요.</div> : null}
          </div>
        </>
      ) : (
        <>
          <DurationField value={dur} onChange={setDur} label={`얼마나 ${mode === "log" ? "했나요" : "할 건가요"}?`} />

          <label className="f">강도 · 몰입도 <span className="dim">({inten}/10, 보통 5)</span></label>
          <div className="row wrap" style={{ gap: 5 }}>
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => (
              <button key={i} className={`chip sm ${inten === i ? "on" : ""}`} style={{ minWidth: 30, justifyContent: "center" }} onClick={() => setInten(i)}>
                {i}
              </button>
            ))}
          </div>

          <WhenField
            ts={startTs}
            onChange={setStartTs}
            now={now}
            label={timeLabel}
            days={mode === "plan" ? [0, 1, 2] : [-1, 0]}
            quick={
              mode === "plan"
                ? null
                : [
                    { label: "지금", ts: () => now },
                    { label: "30분 전", ts: () => now - 30 * 60000 },
                    { label: "1시간 전", ts: () => now - 60 * 60000 },
                    { label: "방금 끝남", ts: () => now - dur * 60000 }
                  ]
            }
          />

          <div className="card" style={{ marginTop: 16, marginBottom: 12 }}>
            <h2>예상 소모</h2>
            <div className="row between" style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 20, fontWeight: 700 }}><CostText hp={pred.hp} mp={pred.mp} /></div>
              {pred.debt > 3 ? <span className="badge yellow">내일 지연피로 {Math.round(pred.debt)}</span> : null}
            </div>
            <Gauge kind="hp" value={state.hp} ghost={after.hp} floor={data.profile.floor} label="HP" note={`→ ${Math.round(after.hp)}`} />
            <Gauge kind="mp" value={state.mp} ghost={after.mp} floor={data.profile.floor} label="MP" note={`→ ${Math.round(after.mp)}`} />
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
