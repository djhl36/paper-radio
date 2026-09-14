import React, { useEffect, useMemo, useState } from "react";
import ActivityPicker from "../components/ActivityPicker.jsx";
import CheckinSheet from "../components/CheckinSheet.jsx";
import BlockTimeline from "../components/BlockTimeline.jsx";
import FeedbackSheet from "../components/FeedbackSheet.jsx";
import { CostText, Empty, Gauge, Sheet, durLabel, hhmm } from "../components/ui.jsx";
import { buildBlocks } from "../engine/blocks.js";
import { dateKey, dayHistory } from "../engine/learn.js";
import { FLAGS, bedTimeOf, budget, simulate, suggestions, verdict } from "../engine/model.js";
import { notifyState, scheduleReminders } from "../engine/notify.js";
import { recommend } from "../engine/recommend.js";
import { recentActivityNames, todayRules } from "../engine/rules.js";
import { useApp } from "../store.js";

const DOW = ["일", "월", "화", "수", "목", "금", "토"];

export default function Today() {
  const { data, dispatch, activities, actById, ctx, today, day, predictFor, vitalsCtx, vitals, state, now } = useApp();
  const [picker, setPicker] = useState(null);
  const [session, setSession] = useState(null);
  const [checkin, setCheckin] = useState(false);
  const [recOpen, setRecOpen] = useState(false);
  const [why, setWhy] = useState(false);
  const [preset, setPreset] = useState(null);

  const bud = budget(vitalsCtx, data.profile, now);

  const planItems = useMemo(
    () =>
      data.plan
        .filter((p) => p.startTs + p.durationMin * 60000 > now && actById[p.actId])
        .map((p) => ({ ...p, act: actById[p.actId] }))
        .sort((a, b) => a.startTs - b.startTs),
    [data.plan, actById, now]
  );

  const simOpt = { now, profile: data.profile };
  const sim = useMemo(() => simulate(planItems, vitalsCtx, simOpt), [planItems, vitalsCtx, now]);
  const vd = verdict(sim, data.profile);
  const tips = useMemo(
    () => (planItems.length ? suggestions(planItems, vitalsCtx, simOpt, 2) : []),
    [planItems, vitalsCtx, now]
  );

  // 계획 N분 전 알림 예약 (앱이 살아 있는 동안)
  useEffect(() => {
    if (!data.calendar.notify) return;
    scheduleReminders(
      planItems.map((p) => ({ ...p, pred: predictFor(p.act, p) })),
      { reminderMin: data.calendar.reminderMin, now }
    );
  }, [planItems, data.calendar.notify, data.calendar.reminderMin]);

  const todayLogs = data.logs.filter((l) => dateKey(new Date(l.startTs)) === today).sort((a, b) => b.startTs - a.startTs);
  const spent = todayLogs.reduce(
    (a, l) => ({ hp: a.hp + Math.max(0, l.actual.hp), mp: a.mp + Math.max(0, l.actual.mp) }),
    { hp: 0, mp: 0 }
  );

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
        state,
        profile: data.profile,
        budget: bud,
        simTotal: { hp: sim.total.planHp, mp: sim.total.planMp }
      }),
    [hist, data.days, data.logs, planItems, state.hp, state.mp, bud.hp, bud.mp, sim.total.planHp]
  );

  const blocks = useMemo(
    () =>
      buildBlocks({
        wakeTs: vitalsCtx.wakeTs,
        bedTs: bedTimeOf(now, data.profile),
        logs: data.logs.filter((l) => dateKey(new Date(l.startTs)) === today),
        plan: data.plan,
        actById,
        now
      }),
    [data.logs, data.plan, actById, vitalsCtx.wakeTs, now, today]
  );

  const rec = useMemo(() => recommend(activities, state, data.profile, predictFor, bud), [activities, state.hp, state.mp, bud.hp, bud.mp]);
  const d = new Date(now);

  return (
    <div>
      <div className="hdr">
        <div>
          <h1>🔋 Today</h1>
          <div className="sub">{d.getMonth() + 1}월 {d.getDate()}일 ({DOW[d.getDay()]}) · 취침까지 {bud.hours}시간</div>
        </div>
        <button className="chip sm" onClick={() => setCheckin(true)}>{day.checkedIn ? "수면 수정" : "체크인"}</button>
      </div>

      {!day.checkedIn ? (
        <button className="verdict yellow" style={{ display: "block", width: "100%", textAlign: "left" }} onClick={() => setCheckin(true)}>
          <div className="t">☀️ 오늘 아침 체크인이 아직입니다</div>
          <div className="d">취침·기상 시각을 넣으면 오늘의 HP·MP가 계산됩니다.</div>
        </button>
      ) : null}

      <div className="card">
        <Gauge kind="hp" value={state.hp} floor={data.profile.floor} label="HP · 몸" />
        <Gauge kind="mp" value={state.mp} floor={data.profile.floor} label="MP · 머리" />
        <div className="row between mt" style={{ paddingTop: 12, borderTop: "1px solid var(--line)" }}>
          <div>
            <div className="sub">오늘 남은 예산</div>
            <div className="mono" style={{ fontSize: 15, fontWeight: 700 }}>
              <span className="cost"><span className="h">HP {Math.round(bud.hp)}</span> <span className="dim">·</span> <span className="m">MP {Math.round(bud.mp)}</span></span>
            </div>
          </div>
          <button className="chip sm" onClick={() => setWhy(true)}>왜 이 값인가</button>
        </div>
        {(day.flags || []).length || vitals.debt > 3 ? (
          <div className="row wrap mt" style={{ gap: 6 }}>
            {(day.flags || []).map((id) => {
              const f = FLAGS.find((x) => x.id === id);
              return f ? <span key={id} className="chip sm">{f.emoji} {f.name}</span> : null;
            })}
            {vitals.debt > 3 ? <span className="chip sm">🩹 지연 근피로 {Math.round(vitals.debt)}</span> : null}
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
              <div className="sub">진행 중 · {hhmm(running.startTs)} 시작</div>
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
              <span className="mono">계획 몫 <CostText hp={sim.total.planHp} mp={sim.total.planMp} /></span>
            </div>
            <div className="row between" style={{ fontSize: 13, marginTop: 4 }}>
              <span className="sub">최저점 / 취침 시</span>
              <span className="mono">{Math.round(sim.min.hp)}·{Math.round(sim.min.mp)} → {Math.round(sim.end.hp)}·{Math.round(sim.end.mp)}</span>
            </div>
            <div className="sub" style={{ marginTop: 4, fontSize: 11.5 }}>
              계획이 없어도 취침 땐 {Math.round(sim.baseline.hp)}·{Math.round(sim.baseline.mp)} — 시간이 흐르는 것만으로 빠지는 몫입니다.
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
          <h2 style={{ margin: 0 }}>하루 블록 ({todayLogs.length}건 기록)</h2>
          <span className="sub">{spent.hp || spent.mp ? `합계 ${Math.round(spent.hp)}·${Math.round(spent.mp)}` : ""}</span>
        </div>
        <BlockTimeline
          slots={blocks}
          onEmpty={(s) => {
            setPreset({ startTs: s.start, durationMin: 30 });
            setPicker("log");
          }}
          onLog={(l) => {
            const a = actById[l.actId];
            if (a) setSession({ ...data.logs.find((x) => x.id === l.id), act: a, logId: l.id });
          }}
          onPlan={(pItem) => {
            const a = actById[pItem.actId];
            if (a) { setPreset({ startTs: pItem.startTs, durationMin: pItem.durationMin }); setPicker("log"); }
          }}
        />
      </div>

      <ActivityPicker
        open={picker !== null}
        mode={picker || "start"}
        presetStart={preset?.startTs || null}
        presetDuration={preset?.durationMin || null}
        onClose={() => { setPicker(null); setPreset(null); }}
        onSubmit={(s) => {
          if (picker === "start") {
            dispatch({ type: "start", now: Date.now(), startTs: s.startTs, actId: s.act.id, durationMin: s.durationMin, intensity: s.intensity });
          } else {
            setSession(s);
          }
        }}
      />

      <FeedbackSheet
        open={!!session}
        session={session}
        onClose={() => setSession(null)}
        onDone={(log) =>
          session?.logId
            ? dispatch({ type: "updateLog", id: session.logId, patch: log })
            : dispatch({ type: "complete", now: Date.now(), log })
        }
        onDelete={(id) => dispatch({ type: "deleteLog", id })}
      />

      <CheckinSheet open={checkin} onClose={() => setCheckin(false)} />

      <Sheet open={why} onClose={() => setWhy(false)} title="지금 값은 이렇게 나왔습니다">
        <div className="sub" style={{ marginBottom: 12 }}>
          Real Life RPG 엔진 그대로입니다 — 잠으로 채운 뒤, 깨어 있는 시간·일주기 리듬·운동·인지 부하로 깎습니다.
        </div>
        {[["HP · 몸", vitals.hpParts, "h"], ["MP · 머리", vitals.mpParts, "m"]].map(([label, parts, cls]) => (
          <div className="card" key={label}>
            <h2>{label}</h2>
            <table className="t">
              <tbody>
                {parts.map(([name, v], i) => (
                  <tr key={i}>
                    <td>{name}</td>
                    <td style={{ color: v >= 0 ? "var(--hp)" : "var(--bad)" }}>{v > 0 ? "+" : ""}{Math.round(v)}</td>
                  </tr>
                ))}
                <tr>
                  <td><strong>합계</strong></td>
                  <td><strong className={`cost ${cls}`}>{Math.round(cls === "h" ? vitals.hp : vitals.mp)}</strong></td>
                </tr>
              </tbody>
            </table>
          </div>
        ))}
        <div className="card">
          <h2>입력값</h2>
          <div className="sub" style={{ lineHeight: 1.7 }}>
            수면 {day.sleepHours ? `${day.sleepHours}시간` : "미입력"}{day.bed ? ` (${day.bed}~${day.wake})` : ""} ·
            수면계수 {Math.round(vitals.detail.sleepCoefficient * 100)}% · 14박 수면부채 −{Math.round(vitals.detail.sleepDebt * 100)}%<br />
            기상 후 {vitals.detail.hoursSinceWake}시간 · 수면압 {Math.round(vitals.detail.pressure * 100)}% ·
            일주기 {vitals.detail.circadian > 0 ? "+" : ""}{Math.round(vitals.detail.circadian * 100)}%<br />
            운동 즉시피로 {Math.round(vitals.detail.fast * 100)} · 지연 근피로 {Math.round(vitals.detail.structural * 100)}
            {vitals.detail.napHours ? ` · 낮잠 ${vitals.detail.napHours}시간` : ""}
          </div>
        </div>
        <button className="btn block" onClick={() => { setWhy(false); setCheckin(true); }}>입력값 고치기</button>
      </Sheet>

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
                dispatch({ type: "start", now: Date.now(), startTs: Date.now(), actId: r.act.id, durationMin: r.act.dur, intensity: 5 });
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
