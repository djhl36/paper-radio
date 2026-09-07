import React, { useEffect, useMemo, useState } from "react";
import ActivityPicker from "../components/ActivityPicker.jsx";
import CheckinSheet from "../components/CheckinSheet.jsx";
import FeedbackSheet from "../components/FeedbackSheet.jsx";
import { CostText, Empty, Gauge, Sheet, durLabel, hhmm } from "../components/ui.jsx";
import { dateKey, dayHistory } from "../engine/learn.js";
import { recentActivityNames, todayRules } from "../engine/rules.js";
import { FLAGS, budget, simulate, suggestions, verdict } from "../engine/model.js";
import { recommend } from "../engine/recommend.js";
import { useApp } from "../store.js";

const DOW = ["일", "월", "화", "수", "목", "금", "토"];

export default function Today() {
  const { data, dispatch, activities, actById, ctx, today, day, predictFor } = useApp();
  const [now, setNow] = useState(Date.now());
  const [picker, setPicker] = useState(null);
  const [session, setSession] = useState(null);
  const [checkin, setCheckin] = useState(false);
  const [recOpen, setRecOpen] = useState(false);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), data.running ? 1000 : 30000);
    return () => clearInterval(t);
  }, [data.running]);

  const bud = budget(data.state, data.profile, now);

  const planItems = useMemo(
    () =>
      data.plan
        .filter((p) => p.startTs + p.durationMin * 60000 > now && actById[p.actId])
        .map((p) => ({ ...p, act: actById[p.actId] }))
        .sort((a, b) => a.startTs - b.startTs),
    [data.plan, actById, now]
  );

  const simOpt = { now, profile: data.profile, ctx, learn: data.learn };
  const sim = useMemo(() => simulate(data.state, planItems, simOpt), [data.state, planItems, now]);
  const vd = verdict(sim, data.profile);
  const tips = useMemo(
    () => (planItems.length ? suggestions(data.state, planItems, simOpt, 2) : []),
    [data.state, planItems, now]
  );

  const todayLogs = data.logs.filter((l) => dateKey(new Date(l.startTs)) === today).sort((a, b) => b.startTs - a.startTs);
  const spent = todayLogs.reduce((a, l) => ({ hp: a.hp + Math.max(0, l.actual.hp), mp: a.mp + Math.max(0, l.actual.mp) }), { hp: 0, mp: 0 });

  const running = data.running && actById[data.running.actId] ? { ...data.running, act: actById[data.running.actId] } : null;
  const elapsedMin = running ? Math.max(1, Math.round((now - running.startTs) / 60000)) : 0;

  const finish = () => {
    setSession({ ...running, durationMin: Math.max(5, Math.round(elapsedMin / 5) * 5) });
    dispatch({ type: "cancel" });
  };

  const hist = useMemo(() => dayHistory(data.days), [data.days]);
  const nameToAct = useMemo(() => Object.fromEntries(activities.map((a) => [a.name, a])), [activities]);
  const rules = useMemo(
    () =>
      todayRules({
        rows: hist,
        days: data.days,
        todayKey: today,
        planItems,
        recentActs: recentActivityNames(data.days, data.logs, actById, today, 7),
        nameToAct,
        state: data.state,
        profile: data.profile,
        budget: bud,
        simTotal: sim.total
      }),
    [hist, data.days, data.logs, planItems, data.state, bud.hp, bud.mp, sim.total.hp]
  );

  const rec = useMemo(() => recommend(activities, data.state, data.profile, predictFor, bud), [activities, data.state, bud.hp, bud.mp]);
  const d = new Date(now);

  return (
    <div>
      <div className="hdr">
        <div>
          <h1>🔋 Today</h1>
          <div className="sub">{d.getMonth() + 1}월 {d.getDate()}일 ({DOW[d.getDay()]}) · 취침까지 {bud.hours}시간</div>
        </div>
        <button className="chip sm" onClick={() => setCheckin(true)}>{day.checkedIn ? "상태 보정" : "체크인"}</button>
      </div>

      {!day.checkedIn ? (
        <button className="verdict yellow" style={{ display: "block", width: "100%", textAlign: "left" }} onClick={() => setCheckin(true)}>
          <div className="t">☀️ 오늘 아침 체크인이 아직입니다</div>
          <div className="d">어젯밤 수면을 알려주면 오늘의 HP·MP를 맞춰 드립니다.</div>
        </button>
      ) : null}

      <div className="card">
        <Gauge kind="hp" value={data.state.hp} floor={data.profile.floor} label="HP · 몸" />
        <Gauge kind="mp" value={data.state.mp} floor={data.profile.floor} label="MP · 머리" />
        <div className="row between mt" style={{ paddingTop: 12, borderTop: "1px solid var(--line)" }}>
          <div>
            <div className="sub">오늘 남은 예산</div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 700 }}>
              <span className="cost"><span className="h">HP {Math.round(bud.hp)}</span> <span className="dim">·</span> <span className="m">MP {Math.round(bud.mp)}</span></span>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="sub">오늘 사용</div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 700 }}>
              {Math.round(spent.hp)} · {Math.round(spent.mp)}
            </div>
          </div>
        </div>
        {(day.flags || []).length || data.state.debt > 2 ? (
          <div className="row wrap mt" style={{ gap: 6 }}>
            {(day.flags || []).map((id) => {
              const f = FLAGS.find((x) => x.id === id);
              return f ? <span key={id} className="chip sm">{f.emoji} {f.name}</span> : null;
            })}
            {data.state.debt > 2 ? <span className="chip sm">🩹 회복부채 {Math.round(data.state.debt)}</span> : null}
          </div>
        ) : null}
      </div>

      {rules.length ? (
        <div className="card">
          <h2>오늘의 규칙</h2>
          <div className="rules">
            {rules.map((r, i) => (
              <div className={`rule ${r.level}`} key={i}>
                <span className="ic">{r.icon}</span>
                <span>
                  <span className="t">{r.title}</span>
                  <span className="d">{r.detail}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {running ? (
        <div className="card running">
          <div className="row between">
            <div>
              <div className="sub">진행 중</div>
              <div style={{ fontSize: 17, fontWeight: 700 }}>{running.act.emoji} {running.act.name}</div>
            </div>
            <div className="big">{String(Math.floor(elapsedMin / 60)).padStart(2, "0")}:{String(elapsedMin % 60).padStart(2, "0")}</div>
          </div>
          <div className="grid2 mt">
            <button className="btn ghost" onClick={() => dispatch({ type: "cancel" })}>취소</button>
            <button className="btn primary" onClick={finish}>종료하고 기록</button>
          </div>
        </div>
      ) : (
        <div className="grid2" style={{ marginBottom: 12, gridTemplateColumns: "1fr 1fr 1fr" }}>
          <button className="btn primary" onClick={() => setPicker("start")}>▶ 시작</button>
          <button className="btn" onClick={() => setPicker("log")}>＋ 기록</button>
          <button className="btn" onClick={() => setRecOpen(true)}>🔎 뭐하지</button>
        </div>
      )}

      {planItems.length ? (
        <>
          <div className={`verdict ${vd.level}`}>
            <div className="t">{vd.emoji} {vd.title}</div>
            <div className="d">{vd.tone}</div>
            <div className="row between mt" style={{ fontSize: 13 }}>
              <span className="sub">남은 계획 {planItems.length}건 · {durLabel(sim.total.min)}</span>
              <span className="mono">예상 소모 <CostText hp={sim.total.hp} mp={sim.total.mp} /></span>
            </div>
            <div className="row between" style={{ fontSize: 13, marginTop: 4 }}>
              <span className="sub">최저점 / 취침 시</span>
              <span className="mono">{Math.round(sim.min.hp)}·{Math.round(sim.min.mp)} → {Math.round(sim.end.hp)}·{Math.round(sim.end.mp)}</span>
            </div>
          </div>

          <div className="card">
            <h2>남은 일정</h2>
            <div className="tl">
              {sim.steps.map((s, i) => (
                <div className="ev" key={i}>
                  <span className="time">{hhmm(s.ts)}</span>
                  <div className="item">
                    <span className="emoji">{s.item.act.emoji}</span>
                    <span className="body">
                      <span className="t">{s.item.act.name}</span>
                      <span className="s">{durLabel(s.item.durationMin)} · 강도 {s.item.intensity}</span>
                    </span>
                    <span className="cost">
                      <CostText hp={s.load.hp} mp={s.load.mp} />
                      <br />
                      <span className="dim">→ {Math.round(s.after.hp)}·{Math.round(s.after.mp)}</span>
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {tips.length ? (
            <div className="card">
              <h2>이렇게 하면 여유가 생깁니다</h2>
              <div className="list">
                {tips.map((t, i) => (
                  <div className="item" key={i}>
                    <span className="emoji">{t.item.act.emoji}</span>
                    <span className="body">
                      <span className="t">{t.item.act.name} {t.item.durationMin}→{t.item.durationMin - t.cut}분</span>
                      <span className="s">최저점 HP +{t.gain.hp} · MP +{t.gain.mp}</span>
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
        </>
      ) : null}

      <div className="card">
        <div className="row between" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>오늘 한 일 ({todayLogs.length})</h2>
        </div>
        {todayLogs.length ? (
          <div className="list">
            {todayLogs.map((l) => {
              const a = actById[l.actId] || { emoji: "❓", name: l.actId };
              return (
                <div className="item" key={l.id}>
                  <span className="emoji">{a.emoji}</span>
                  <span className="body">
                    <span className="t">{a.name}</span>
                    <span className="s">{hhmm(l.startTs)} · {durLabel(l.durationMin)}{l.note ? ` · ${l.note}` : ""}</span>
                  </span>
                  <span className="cost"><CostText hp={l.actual.hp} mp={l.actual.mp} /></span>
                </div>
              );
            })}
          </div>
        ) : (
          <Empty>아직 기록이 없습니다. 활동을 시작하거나 끝난 일을 기록해 보세요.</Empty>
        )}
      </div>

      <ActivityPicker
        open={picker !== null}
        mode={picker || "start"}
        onClose={() => setPicker(null)}
        onSubmit={(s) => {
          if (picker === "start") {
            dispatch({ type: "start", now: Date.now(), actId: s.act.id, durationMin: s.durationMin, intensity: s.intensity });
          } else {
            setSession(s);
          }
        }}
      />

      <FeedbackSheet
        open={!!session}
        session={session}
        onClose={() => setSession(null)}
        onDone={(log) => dispatch({ type: "complete", now: Date.now(), log })}
      />

      <CheckinSheet open={checkin} onClose={() => setCheckin(false)} />

      <Sheet open={recOpen} onClose={() => setRecOpen(false)} title="🔎 지금 뭐 하지?">
        <div className="sub" style={{ marginBottom: 12 }}>
          남은 예산 HP {Math.round(bud.hp)} · MP {Math.round(bud.mp)} 기준입니다.
        </div>
        <h2 style={{ fontSize: 13, color: "var(--sub)" }}>지금 하기 좋은 것</h2>
        <div className="list" style={{ marginBottom: 16 }}>
          {rec.good.slice(0, 6).map((r) => (
            <button
              className="item tap"
              key={r.act.id}
              onClick={() => {
                setRecOpen(false);
                dispatch({ type: "start", now: Date.now(), actId: r.act.id, durationMin: r.act.dur, intensity: 5 });
              }}
            >
              <span className="emoji">{r.act.emoji}</span>
              <span className="body">
                <span className="t">{r.act.name}</span>
                <span className="s">{durLabel(r.act.dur)} · 여유 {Math.round(r.margin)}</span>
              </span>
              <span className="cost"><CostText hp={r.pred.hp} mp={r.pred.mp} /></span>
            </button>
          ))}
        </div>
        {rec.avoid.length ? (
          <>
            <h2 style={{ fontSize: 13, color: "var(--sub)" }}>지금은 피하는 게 좋은 것</h2>
            <div className="list">
              {rec.avoid.slice(0, 3).map((r) => (
                <div className="item" key={r.act.id} style={{ opacity: 0.72 }}>
                  <span className="emoji">{r.act.emoji}</span>
                  <span className="body">
                    <span className="t">{r.act.name}</span>
                    <span className="s">예비분보다 {Math.abs(Math.round(r.margin))} 부족</span>
                  </span>
                  <span className="cost"><CostText hp={r.pred.hp} mp={r.pred.mp} /></span>
                </div>
              ))}
            </div>
          </>
        ) : null}
      </Sheet>
    </div>
  );
}
