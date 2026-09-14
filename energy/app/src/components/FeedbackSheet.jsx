import React, { useEffect, useState } from "react";
import { FEEL_SCALE, REST_SCALE } from "../engine/learn.js";
import { r1 } from "../engine/model.js";
import { useApp } from "../store.js";
import { CostText, DurationField, Feel, Sheet, WhenField } from "./ui.jsx";

const OUT = ["거의 못함", "조금", "보통", "잘함", "최고"];

/** 비율에서 가장 가까운 4단계 눈금 찾기 (기록 수정 시 원래 답을 되살린다) */
const feelIndexOf = (scale, r) => {
  if (r == null) return 1;
  let best = 1;
  let diff = Infinity;
  scale.forEach((s, i) => {
    const d = Math.abs(s.r - r);
    if (d < diff) { diff = d; best = i; }
  });
  return best;
};

/**
 * 활동 종료 후 피드백. 사용자는 "앱 예상 대비 어땠는지"만 답한다.
 * session: { act, durationMin, intensity, startTs, logId?, ratio?, output?, note? }
 * logId 가 있으면 기존 기록을 고치는 모드.
 */
export default function FeedbackSheet({ open, session, onClose, onDone, onDelete }) {
  const { predictFor, state, now } = useApp();
  const [dur, setDur] = useState(60);
  const [startTs, setStartTs] = useState(Date.now());
  const [intensity, setIntensity] = useState(5);
  const [hpFeel, setHpFeel] = useState(1);
  const [mpFeel, setMpFeel] = useState(1);
  const [output, setOutput] = useState(null);
  const [note, setNote] = useState("");

  const editing = !!session?.logId;

  useEffect(() => {
    if (!session) return;
    const restorative = session.act.hp < 0 || session.act.mp < 0;
    const scale = restorative ? REST_SCALE : FEEL_SCALE;
    setDur(session.durationMin || 60);
    setStartTs(session.startTs || Date.now());
    setIntensity(session.intensity ?? 5);
    setHpFeel(feelIndexOf(scale, session.ratio?.hp));
    setMpFeel(feelIndexOf(scale, session.ratio?.mp));
    setOutput(session.output != null ? session.output - 1 : null);
    setNote(session.note || "");
  }, [session?.logId, session?.startTs, session?.act?.id]);

  if (!session) return null;
  const act = session.act;
  const restorative = act.hp < 0 || act.mp < 0;
  const scale = restorative ? REST_SCALE : FEEL_SCALE;
  const pred = predictFor(act, { durationMin: dur, intensity });
  const askHp = Math.abs(pred.hp) >= 3;
  const askMp = Math.abs(pred.mp) >= 3;

  const rHp = askHp ? scale[hpFeel].r : 1;
  const rMp = askMp ? scale[mpFeel].r : 1;
  const actual = { hp: r1(pred.hp * rHp), mp: r1(pred.mp * rMp) };

  const submit = () => {
    onDone({
      actId: act.id,
      startTs,
      durationMin: dur,
      intensity,
      pred,
      actual,
      ratio: { hp: rHp, mp: rMp },
      output: output == null ? null : output + 1,
      note: note.trim() || null
    });
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title={`${act.emoji} ${act.name} · ${editing ? "기록 수정" : "어땠나요?"}`}>
      <div className="sub" style={{ marginBottom: 12 }}>
        앱의 예상은 <CostText hp={pred.hp} mp={pred.mp} /> 였습니다. 체감과 비교해 주세요.
      </div>

      <DurationField value={dur} onChange={setDur} label="실제 시간" />

      <WhenField ts={startTs} onChange={setStartTs} now={now} label="시작 시각" days={[-1, 0]} />

      <label className="f">강도 · 몰입도 <span className="dim">({intensity}/10, 보통 5)</span></label>
      <div className="row wrap" style={{ gap: 5 }}>
        {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((i) => (
          <button key={i} className={`chip sm ${intensity === i ? "on" : ""}`} style={{ minWidth: 30, justifyContent: "center" }} onClick={() => setIntensity(i)}>
            {i}
          </button>
        ))}
      </div>

      {askHp ? (
        <>
          <label className="f">💪 몸은 {restorative ? "얼마나 회복됐나요?" : "얼마나 힘들었나요?"}</label>
          <Feel scale={scale} value={hpFeel} onChange={setHpFeel} />
        </>
      ) : null}
      {askMp ? (
        <>
          <label className="f">🧠 머리는 {restorative ? "얼마나 개운한가요?" : "얼마나 지쳤나요?"}</label>
          <Feel scale={scale} value={mpFeel} onChange={setMpFeel} />
        </>
      ) : null}

      {act.out ? (
        <>
          <label className="f">📈 성과는? <span className="dim">(선택 — 최적 지속시간 분석에 쓰입니다)</span></label>
          <div className="feel">
            {OUT.map((l, i) => (
              <button key={i} className={output === i ? "on" : ""} onClick={() => setOutput(output === i ? null : i)}>
                <span className="e" style={{ fontSize: 15, fontWeight: 700 }}>{i + 1}</span>
                <span className="l">{l}</span>
              </button>
            ))}
          </div>
        </>
      ) : null}

      <label className="f">메모 <span className="dim">(선택)</span></label>
      <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="예: 3세트 후반부터 다리 무거움" />

      <div className="card" style={{ marginTop: 16 }}>
        <div className="row between">
          <span className="sub">실제 반영값</span>
          <strong><CostText hp={actual.hp} mp={actual.mp} /></strong>
        </div>
        <div className="row between mt">
          <span className="sub">반영 후</span>
          <strong className="mono">
            HP {Math.round(Math.max(0, state.hp - actual.hp))} · MP {Math.round(Math.max(0, state.mp - actual.mp))}
          </strong>
        </div>
      </div>

      {editing ? (
        <div className="grid2" style={{ marginTop: 14 }}>
          <button
            className="btn danger"
            onClick={() => { if (confirm("이 기록을 지울까요?")) { onDelete?.(session.logId); onClose(); } }}
          >
            삭제
          </button>
          <button className="btn primary" onClick={submit}>저장</button>
        </div>
      ) : (
        <button className="btn primary block" style={{ marginTop: 14 }} onClick={submit}>완료</button>
      )}
    </Sheet>
  );
}
