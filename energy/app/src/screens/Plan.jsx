import React, { useEffect, useMemo, useRef, useState } from "react";
import ActivityPicker from "../components/ActivityPicker.jsx";
import { CostText, Empty, Gauge, Seg, durLabel, hhmm } from "../components/ui.jsx";
import { buildICS, downloadText, fetchICS, googleCalendarUrl, guessActivity, parseICS } from "../engine/calendar.js";
import { dateKey } from "../engine/learn.js";
import { simulate, suggestions, verdict } from "../engine/model.js";
import { timeOnDate, useApp } from "../store.js";

const dayStart = (offset) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
};

export default function Plan() {
  const { data, dispatch, actById, activities, vitalsCtx, predictFor, now } = useApp();
  const [offset, setOffset] = useState(0);
  const [picker, setPicker] = useState(false);
  const [imported, setImported] = useState(null);
  const fileRef = useRef(null);

  const from = dayStart(offset);
  const to = from + 86400000;
  const key = dateKey(new Date(from));

  const items = useMemo(
    () =>
      data.plan
        .filter((p) => p.startTs >= from && p.startTs < to && actById[p.actId])
        .map((p) => ({ ...p, act: actById[p.actId] }))
        .sort((a, b) => a.startTs - b.startTs),
    [data.plan, actById, from]
  );

  // 오늘은 지금 상태에서, 이후 날짜는 "목표만큼 자고 일어난 아침"에서 출발한다
  const { ctx, startTs } = useMemo(() => {
    if (offset === 0) return { ctx: vitalsCtx, startTs: now };
    const wakeTs = timeOnDate(key, null, data.profile.wakeHour);
    const todayNight = (data.days[dateKey(new Date())]?.sleepHours || data.profile.sleepTarget) * 60;
    return {
      ctx: {
        ...vitalsCtx,
        wakeTs,
        sleep: { minutes: data.profile.sleepTarget * 60, quality: 0.75 },
        nights: [todayNight, ...vitalsCtx.nights].slice(0, 14),
        sessions: [],
        flags: []
      },
      startTs: wakeTs
    };
  }, [offset, vitalsCtx, key, now]);

  const simOpt = { now: Math.max(startTs, offset === 0 ? now : startTs), profile: data.profile };
  const sim = simulate(items, ctx, simOpt);
  const vd = verdict(sim, data.profile);
  const tips = items.length ? suggestions(items, ctx, simOpt, 2) : [];

  const addAt = (s) => {
    const src = new Date(s.startTs);
    const d = new Date(from);
    d.setHours(src.getHours(), src.getMinutes(), 0, 0);
    dispatch({ type: "planAdd", item: { actId: s.act.id, durationMin: s.durationMin, intensity: s.intensity, startTs: d.getTime() } });
  };

  // 구독 주소가 있으면 앱을 열 때 한 번 자동으로 읽어 계획에 반영한다
  const [autoMsg, setAutoMsg] = useState(null);
  useEffect(() => {
    if (!data.calendar.autoImport || !data.calendar.url) return;
    if (data.calendar.lastSync && Date.now() - data.calendar.lastSync < 30 * 60000) return;
    let alive = true;
    (async () => {
      try {
        const events = await fetchICS(data.calendar.url);
        if (!alive) return;
        const items = events
          .filter((ev) => !ev.allDay && ev.start >= dayStart(0) && ev.start < dayStart(8))
          .map((ev) => ({ ev, g: guessActivity(ev.summary, activities) }))
          .filter((x) => x.g)
          .map(({ ev, g }) => ({
            actId: g.act.id, durationMin: ev.durationMin, intensity: g.intensity ?? 5,
            startTs: ev.start, uid: ev.uid, title: ev.summary
          }));
        dispatch({ type: "calendar", patch: { lastSync: Date.now() } });
        if (items.length) {
          dispatch({ type: "planAddMany", items });
          setAutoMsg(`캘린더에서 ${items.length}건을 자동으로 담았습니다.`);
        }
      } catch {
        if (alive) setAutoMsg("구독 주소를 자동으로 읽지 못했습니다 (설정에서 .ics 파일로 가져오세요).");
      }
    })();
    return () => { alive = false; };
  }, [data.calendar.autoImport, data.calendar.url]);

  // ── 캘린더 ──
  const importFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => {
      try {
        const events = parseICS(String(r.result))
          .filter((ev) => !ev.allDay && ev.start >= dayStart(0) && ev.start < dayStart(8))
          .slice(0, 60)
          .map((ev) => ({ ...ev, match: guessActivity(ev.summary, activities), use: true }));
        setImported(events.length ? events : { error: "다음 7일 안에 시간이 있는 일정이 없습니다." });
      } catch (err) {
        setImported({ error: err?.message || "파일을 읽지 못했습니다." });
      }
    };
    r.readAsText(f);
    e.target.value = "";
  };

  const confirmImport = () => {
    const add = imported
      .filter((ev) => ev.use && ev.match)
      .map((ev) => ({
        actId: ev.match.act.id,
        durationMin: ev.durationMin,
        intensity: ev.match.intensity ?? 5,
        startTs: ev.start,
        uid: ev.uid,
        title: ev.summary
      }));
    if (add.length) dispatch({ type: "planAddMany", items: add });
    setImported(null);
  };

  const exportICS = () => {
    const all = data.plan
      .filter((p) => actById[p.actId] && p.startTs > now - 86400000)
      .map((p) => ({ ...p, act: actById[p.actId], pred: predictFor(actById[p.actId], p) }));
    if (!all.length) return;
    downloadText(buildICS(all, { reminderMin: data.calendar.reminderMin }), "energy-plan.ics");
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

      {autoMsg ? (
        <div className="verdict green" style={{ padding: "10px 12px" }}>
          <div className="d" style={{ color: "var(--sub)", marginTop: 0 }}>{autoMsg}</div>
        </div>
      ) : null}

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
                <div className="sub">계획 몫 소모</div>
                <div style={{ fontSize: 17, fontWeight: 700 }}><CostText hp={sim.total.planHp} mp={sim.total.planMp} /></div>
              </div>
            </div>
            <Gauge kind="hp" value={sim.start.hp} ghost={sim.min.hp} floor={data.profile.floor} label="HP · 시작 → 최저" note={`↓ ${Math.round(sim.min.hp)}`} />
            <Gauge kind="mp" value={sim.start.mp} ghost={sim.min.mp} floor={data.profile.floor} label="MP · 시작 → 최저" note={`↓ ${Math.round(sim.min.mp)}`} />
            <div className="sub mt">
              하루를 마치면 HP {Math.round(sim.end.hp)} · MP {Math.round(sim.end.mp)}
              <span className="dim"> (계획이 없으면 {Math.round(sim.baseline.hp)}·{Math.round(sim.baseline.mp)})</span>
            </div>
          </div>
        </>
      ) : null}

      <div className="card">
        <div className="row between" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>일정</h2>
          <div className="row" style={{ gap: 6 }}>
            <button className="chip sm" onClick={() => fileRef.current?.click()}>📥 캘린더</button>
            <button className="chip sm" onClick={() => setPicker(true)}>＋ 추가</button>
          </div>
        </div>
        <input ref={fileRef} type="file" accept=".ics,text/calendar" style={{ display: "none" }} onChange={importFile} />
        {items.length ? (
          <div className="tl">
            {sim.steps.map((s) => (
              <div className="ev" key={s.item.id}>
                <span className="time">{hhmm(s.item.startTs)}</span>
                <div className="item">
                  <span className="emoji">{s.item.act.emoji}</span>
                  <span className="body">
                    <span className="t">{s.item.title || s.item.act.name}</span>
                    <span className="s">
                      {durLabel(s.item.durationMin)} · 강도 {s.item.intensity} · 이후 {Math.round(s.after.hp)}·{Math.round(s.after.mp)}
                      {s.ts - s.item.startTs > 600000 ? ` · 겹침 → ${hhmm(s.ts)} 시작` : ""}
                    </span>
                  </span>
                  <span className="cost"><CostText hp={s.load.hp} mp={s.load.mp} /></span>
                  <a
                    className="chip sm" title="구글 캘린더에 추가" target="_blank" rel="noreferrer"
                    href={googleCalendarUrl({ ...s.item, pred: predictFor(s.item.act, s.item) })}
                  >
                    📅
                  </a>
                  <button className="chip sm" onClick={() => dispatch({ type: "planRemove", id: s.item.id })}>✕</button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Empty>아직 계획이 없습니다. ＋ 추가하거나 캘린더에서 가져오세요.</Empty>
        )}
        {data.plan.length ? (
          <button className="btn ghost block mt" onClick={exportICS}>
            📤 캘린더로 내보내기 (.ics · {data.calendar.reminderMin}분 전 알림 포함)
          </button>
        ) : null}
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

      {imported ? (
        <>
          <div className="backdrop" onClick={() => setImported(null)} />
          <div className="sheet">
            <div className="sheet-wrap">
              <div className="grab" />
              <h3>📥 캘린더에서 가져오기</h3>
              {imported.error ? (
                <div className="empty">{imported.error}</div>
              ) : (
                <>
                  <div className="sub" style={{ marginBottom: 12 }}>
                    활동을 못 찾은 일정은 회색으로 표시됩니다. 활동 탭에서 같은 이름으로 만들면 다음부터 자동으로 연결됩니다.
                  </div>
                  <div className="list">
                    {imported.map((ev, i) => (
                      <button
                        className="item tap"
                        key={ev.uid + i}
                        style={{ opacity: ev.match ? 1 : 0.45 }}
                        onClick={() => setImported(imported.map((x, j) => (j === i ? { ...x, use: !x.use } : x)))}
                      >
                        <span className="emoji">{ev.match ? (ev.use ? "✅" : "⬜") : "❔"}</span>
                        <span className="body">
                          <span className="t">{ev.summary}</span>
                          <span className="s">
                            {new Date(ev.start).getMonth() + 1}/{new Date(ev.start).getDate()} {hhmm(ev.start)} · {durLabel(ev.durationMin)}
                            {ev.match ? ` → ${ev.match.act.emoji} ${ev.match.act.name}` : " · 매칭 없음"}
                          </span>
                        </span>
                      </button>
                    ))}
                  </div>
                  <button className="btn primary block" style={{ marginTop: 14 }} onClick={confirmImport}>
                    {imported.filter((e) => e.use && e.match).length}건 계획에 추가
                  </button>
                </>
              )}
              <button className="btn ghost block mt" onClick={() => setImported(null)}>닫기</button>
            </div>
          </div>
        </>
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
