import React, { useEffect } from "react";

export const hhmm = (ts) => {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

export const durLabel = (m) => {
  m = Math.round(m);
  if (m < 60) return `${m}분`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h}시간 ${r}분` : `${h}시간`;
};

/** 한글 받침에 맞춰 조사를 고른다 ("테니스는", "수업은") */
export function josa(word, pair = "은는") {
  const [withJong, without] = [pair[0], pair[1]];
  const c = String(word || "").trim().slice(-1).charCodeAt(0);
  if (Number.isNaN(c) || c < 0xac00 || c > 0xd7a3) return without;
  return (c - 0xac00) % 28 ? withJong : without;
}

export const signed = (v) => (v > 0 ? `-${Math.round(v)}` : `+${Math.round(Math.abs(v))}`);

/** HP/MP 게이지. ghost = 예상 소모 후 위치 */
export function Gauge({ kind, value, ghost, floor, label, note }) {
  const v = Math.max(0, Math.min(100, value));
  const g = ghost == null ? null : Math.max(0, Math.min(100, ghost));
  return (
    <div className={`gauge ${kind}`}>
      <div className="top">
        <span className="name">{label || kind.toUpperCase()}</span>
        <span className="val">
          {Math.round(v)}
          <small>/100</small>
          {note ? <small style={{ marginLeft: 8 }}>{note}</small> : null}
        </span>
      </div>
      <div className="bar">
        <i style={{ width: `${v}%` }} />
        {g != null && g < v ? <span className="ghost" style={{ left: `${g}%`, width: `${v - g}%` }} /> : null}
        {floor != null ? <span className="floor" style={{ left: `${floor}%` }} /> : null}
      </div>
    </div>
  );
}

export function Sheet({ open, onClose, title, children }) {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);
  if (!open) return null;
  return (
    <>
      <div className="backdrop" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true">
        <div className="sheet-wrap">
          <div className="grab" />
          {title ? <h3>{title}</h3> : null}
          {children}
        </div>
      </div>
    </>
  );
}

export function Seg({ options, value, onChange }) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={o.value} className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Feel({ scale, value, onChange }) {
  return (
    <div className="feel">
      {scale.map((s, i) => (
        <button key={i} className={value === i ? "on" : ""} onClick={() => onChange(i)}>
          <span className="e">{s.emoji}</span>
          <span className="l">{s.label}</span>
        </button>
      ))}
    </div>
  );
}

export function CostText({ hp, mp }) {
  return (
    <span>
      <span className="h">HP {signed(hp)}</span>
      <span className="dim"> · </span>
      <span className="m">MP {signed(mp)}</span>
    </span>
  );
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

const QUICK_MIN = [15, 30, 45, 60, 90, 120];

/** 소요 시간: 칩으로 고르거나 분을 직접 친다 */
export function DurationField({ value, onChange, label = "얼마나" }) {
  return (
    <>
      <label className="f">{label} <span className="dim">({durLabel(value || 0)})</span></label>
      <div className="row wrap" style={{ gap: 6, marginBottom: 8 }}>
        {QUICK_MIN.map((m) => (
          <button key={m} className={`chip sm ${value === m ? "on" : ""}`} onClick={() => onChange(m)}>{durLabel(m)}</button>
        ))}
      </div>
      <div className="row" style={{ gap: 8 }}>
        <input
          type="number" inputMode="numeric" min="1" max="1440" step="5" value={value}
          onChange={(e) => onChange(Math.max(1, Math.min(1440, +e.target.value || 0)))}
          style={{ flex: 1 }}
        />
        <span className="sub" style={{ whiteSpace: "nowrap" }}>분</span>
        <button className="chip sm" onClick={() => onChange(Math.max(5, value - 15))}>−15</button>
        <button className="chip sm" onClick={() => onChange(Math.min(1440, value + 15))}>+15</button>
      </div>
    </>
  );
}

const pad2 = (n) => String(n).padStart(2, "0");
export const tsToTime = (ts) => { const d = new Date(ts); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
const dayDiff = (ts, now) => {
  const a = new Date(ts); a.setHours(0, 0, 0, 0);
  const b = new Date(now); b.setHours(0, 0, 0, 0);
  return Math.round((a - b) / 86400000);
};

/** 시각: 날짜는 칩으로, 시각은 직접 입력 */
export function WhenField({ ts, onChange, now = Date.now(), label = "언제", days = [-1, 0, 1], quick = null }) {
  const offset = dayDiff(ts, now);
  const setOffset = (off) => {
    const d = new Date(now);
    d.setDate(d.getDate() + off);
    const cur = new Date(ts);
    d.setHours(cur.getHours(), cur.getMinutes(), 0, 0);
    onChange(d.getTime());
  };
  const setTime = (v) => {
    const [h, m] = String(v).split(":").map(Number);
    if (!Number.isFinite(h)) return;
    const d = new Date(ts);
    d.setHours(h, m || 0, 0, 0);
    onChange(d.getTime());
  };
  const name = (off) => (off === 0 ? "오늘" : off === -1 ? "어제" : off === 1 ? "내일" : off === -2 ? "그제" : `${off > 0 ? "+" : ""}${off}일`);

  return (
    <>
      <label className="f">{label} <span className="dim">({name(offset)} {tsToTime(ts)})</span></label>
      <div className="row" style={{ gap: 8 }}>
        <div className="seg" style={{ flex: 1 }}>
          {days.map((off) => (
            <button key={off} className={offset === off ? "on" : ""} onClick={() => setOffset(off)}>{name(off)}</button>
          ))}
        </div>
        <input type="time" value={tsToTime(ts)} onChange={(e) => setTime(e.target.value)} style={{ width: 138, flex: "0 0 auto", padding: "11px 8px" }} />
      </div>
      {quick?.length ? (
        <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
          {quick.map((q) => (
            <button key={q.label} className="chip sm" onClick={() => onChange(q.ts())}>{q.label}</button>
          ))}
        </div>
      ) : null}
    </>
  );
}
