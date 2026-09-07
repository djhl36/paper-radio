import React, { useMemo, useState } from "react";
import ActivityPicker from "../components/ActivityPicker.jsx";
import { CostText, Empty, Gauge, Seg, durLabel, hhmm } from "../components/ui.jsx";
import { sleepRecover, simulate, suggestions, verdict } from "../engine/model.js";
import { useApp } from "../store.js";

const dayStart = (offset) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
};

export default function Plan() {
  const { data, dispatch, actById, ctx } = useApp();
  const [offset, setOffset] = useState(0);
  const [picker, setPicker] = useState(false);
  const now = Date.now();

  const from = dayStart(offset);
  const to = from + 86400000;

  const items = useMemo(
    () =>
      data.plan
        .filter((p) => p.startTs >= from && p.startTs < to && actById[p.actId])
        .map((p) => ({ ...p, act: actById[p.actId] }))
        .sort((a, b) => a.startTs - b.startTs),
    [data.plan, actById, from]
  );

  // 오늘이면 현재 상태에서, 내일이면 "오늘을 마치고 잠든 뒤" 상태에서 출발한다.
  const { startState, startTs } = useMemo(() => {
    if (offset === 0) return { startState: data.state, startTs: now };
    const todayItems = data.plan
      .filter((p) => p.startTs + p.durationMin * 60000 > now && p.startTs < dayStart(1) && actById[p.actId])
      .map((p) => ({ ...p, act: actById[p.actId] }));
    const endToday = simulate(data.state, todayItems, { now, profile: data.profile, ctx, learn: data.learn }).end;
    // 하루 건너뛸 때마다 잠을 한 번 더 잔 것으로 본다 (모레 = 두 밤 뒤)
    let morning = endToday;
    for (let i = 0; i < offset; i++) morning = sleepRecover(morning, data.profile.sleepTarget, 0.8);
    const wake = new Date(from);
    wake.setHours(data.profile.wakeHour, 0, 0, 0);
    return { startState: morning, startTs: Math.max(wake.getTime(), from) };
  }, [offset, data.state, data.plan, actById, from]);

  const simOpt = {
    now: startTs,
    profile: data.profile,
    ctx: offset === 0 ? ctx : { ...ctx, sleepHours: data.profile.sleepTarget, flags: [] },
    learn: data.learn
  };
  const sim = simulate(startState, items, simOpt);
  const vd = verdict(sim, data.profile);
  const tips = items.length ? suggestions(startState, items, simOpt, 2) : [];

  const addAt = (s) => {
    // 선택한 시각을 대상 날짜에 맞춰 다시 고정
    const src = new Date(s.startTs);
    const d = new Date(from);
    d.setHours(src.getHours(), src.getMinutes(), 0, 0);
    dispatch({
      type: "planAdd",
      item: { actId: s.act.id, durationMin: s.durationMin, intensity: s.intensity, startTs: d.getTime() }
    });
  };

  return (
    <div>
      <div className="hdr">
        <div>
          <h1>🗓️ 계획</h1>
          <div className="sub">시간을 넣으면 에너지로 환산해 드립니다</div>
        </div>
      </div>

      <div style={{ marginBottom: 12 }}>
        <Seg
          options={[{ value: 0, label: "오늘" }, { value: 1, label: "내일" }, { value: 2, label: "모레" }]}
          value={offset}
          onChange={setOffset}
        />
      </div>

      {items.length ? (
        <>
          <div className={`verdict ${vd.level}`}>
            <div className="t">{vd.emoji} {vd.title}</div>
            <div className="d">{vd.tone}</div>
          </div>

          <div className="card">
            <div className="row between" style={{ marginBottom: 12 }}>
              <div>
                <div className="sub">계획된 시간</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{durLabel(sim.total.min)}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="sub">예상 소모</div>
                <div style={{ fontSize: 17, fontWeight: 700 }}><CostText hp={sim.total.hp} mp={sim.total.mp} /></div>
              </div>
            </div>
            <Gauge kind="hp" value={startState.hp} ghost={sim.min.hp} floor={data.profile.floor} label="HP · 시작 → 최저" note={`↓ ${Math.round(sim.min.hp)}`} />
            <Gauge kind="mp" value={startState.mp} ghost={sim.min.mp} floor={data.profile.floor} label="MP · 시작 → 최저" note={`↓ ${Math.round(sim.min.mp)}`} />
            <div className="sub mt">하루를 마치면 HP {Math.round(sim.end.hp)} · MP {Math.round(sim.end.mp)} 로 예상됩니다.</div>
          </div>
        </>
      ) : null}

      <div className="card">
        <div className="row between" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>일정</h2>
          <button className="chip sm" onClick={() => setPicker(true)}>＋ 추가</button>
        </div>
        {items.length ? (
          <div className="tl">
            {sim.steps.map((s, i) => (
              <div className="ev" key={s.item.id}>
                <span className="time">{hhmm(s.item.startTs)}</span>
                <div className="item">
                  <span className="emoji">{s.item.act.emoji}</span>
                  <span className="body">
                    <span className="t">{s.item.act.name}</span>
                    <span className="s">
                      {durLabel(s.item.durationMin)} · 강도 {s.item.intensity} · 이후 {Math.round(s.after.hp)}·{Math.round(s.after.mp)}
                      {s.ts - s.item.startTs > 600000 ? ` · 겹침 → ${hhmm(s.ts)} 시작` : ""}
                    </span>
                  </span>
                  <span className="cost"><CostText hp={s.load.hp} mp={s.load.mp} /></span>
                  <button className="chip sm" onClick={() => dispatch({ type: "planRemove", id: s.item.id })}>✕</button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty>아직 계획이 없습니다. ＋ 추가로 하루를 채워 보세요.</Empty>
        )}
      </div>

      {tips.length ? (
        <div className="card">
          <h2>조정 제안</h2>
          <div className="list">
            {tips.map((t, i) => (
              <div className="item" key={i}>
                <span className="emoji">{t.item.act.emoji}</span>
                <span className="body">
                  <span className="t">{t.item.act.name} {t.item.durationMin}→{t.item.durationMin - t.cut}분</span>
                  <span className="s">최저점 HP +{t.gain.hp} · MP +{t.gain.mp} · 마감 {Math.round(t.end.hp)}·{Math.round(t.end.mp)}</span>
                </span>
                <button
                  className="chip sm"
                  onClick={() => dispatch({ type: "planUpdate", id: t.item.id, patch: { durationMin: t.item.durationMin - t.cut } })}
                >
                  적용
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <ActivityPicker
        open={picker}
        mode="plan"
        defaultTime={`${String(Math.min(23, new Date().getHours() + 1)).padStart(2, "0")}:00`}
        onClose={() => setPicker(false)}
        onSubmit={addAt}
      />
    </div>
  );
}
