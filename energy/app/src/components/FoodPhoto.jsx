import React, { useRef, useState } from "react";
import { analyzeFoodPhoto, shrinkImage } from "../engine/food.js";
import { useApp } from "../store.js";

/** 사진 한 장 → 영양 추정. 결과를 누르면 그날 기록에 반영된다. */
export default function FoodPhoto({ onApply }) {
  const { data } = useApp();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [result, setResult] = useState(null);
  const ref = useRef(null);

  const pick = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    setErr(null);
    setResult(null);
    setBusy(true);
    try {
      const dataUrl = await shrinkImage(f);
      const r = await analyzeFoodPhoto({ apiKey: data.ai.apiKey, dataUrl, model: data.ai.model });
      setResult(r);
    } catch (e2) {
      setErr(e2?.message || "판별에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn" style={{ flex: 1 }} disabled={busy} onClick={() => ref.current?.click()}>
          {busy ? "판별 중…" : "📷 사진으로 추정"}
        </button>
        <input ref={ref} type="file" accept="image/*" capture="environment" style={{ display: "none" }} onChange={pick} />
      </div>
      {!data.ai.apiKey ? (
        <div className="sub" style={{ marginTop: 6, fontSize: 11.5 }}>
          설정 → AI에서 Anthropic API 키를 넣으면 사진 판별을 쓸 수 있습니다.
        </div>
      ) : null}
      {err ? <div className="sub" style={{ marginTop: 8, color: "var(--bad)" }}>{err}</div> : null}
      {result ? (
        <div className="card" style={{ marginTop: 10 }}>
          <div className="row between">
            <strong style={{ fontSize: 14 }}>{result.items.join(", ") || "음식을 찾지 못함"}</strong>
            <span className={`badge ${result.quality === 2 ? "green" : result.quality === 1 ? "yellow" : "red"}`}>
              {["부실", "보통", "충분"][result.quality]}
            </span>
          </div>
          <div className="sub mt mono">
            {result.kcal != null ? `${result.kcal} kcal` : "열량 미상"}
            {result.protein != null ? ` · 단백질 ${result.protein}g` : ""}
            {result.carb != null ? ` · 탄수 ${result.carb}g` : ""}
            {result.fat != null ? ` · 지방 ${result.fat}g` : ""}
          </div>
          {result.note ? <div className="sub" style={{ marginTop: 6 }}>{result.note}</div> : null}
          <div className="grid2 mt">
            <button className="btn ghost" onClick={() => setResult(null)}>버리기</button>
            <button className="btn primary" onClick={() => { onApply?.(result); setResult(null); }}>이 값으로 기록</button>
          </div>
        </div>
      ) : null}
    </>
  );
}
