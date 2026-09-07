import React, { useState } from "react";
import Insights from "./screens/Insights.jsx";
import Library from "./screens/Library.jsx";
import Plan from "./screens/Plan.jsx";
import Settings from "./screens/Settings.jsx";
import Today from "./screens/Today.jsx";
import { AppProvider } from "./store.js";

const TABS = [
  { id: "today", ic: "🔋", label: "오늘", C: Today },
  { id: "plan", ic: "🗓️", label: "계획", C: Plan },
  { id: "lib", ic: "📚", label: "활동", C: Library },
  { id: "insight", ic: "📊", label: "인사이트", C: Insights },
  { id: "settings", ic: "⚙️", label: "설정", C: Settings }
];

export default function App() {
  const [tab, setTab] = useState("today");
  const Cur = TABS.find((t) => t.id === tab).C;
  return (
    <AppProvider>
      <div className="app">
        <Cur />
      </div>
      <nav className="tabbar">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "on" : ""} onClick={() => setTab(t.id)}>
            <span className="ic">{t.ic}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </nav>
    </AppProvider>
  );
}
