import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { navigate } from '../App.jsx'
import { Radar, Donut, BarList } from '../components/Charts.jsx'

const AXIS_KO = {
  aggression: '공격성', power: '파워', consistency: '안정성', net_play: '네트',
  serve: '서브', return_game: '리턴', variety: '다양성', depth: '깊이',
  movement: '활동량', forehand_bias: '포핸드',
}

export default function Profile({ ctx, playerId }) {
  const { me } = ctx
  const [p, setP] = useState(null)
  const [compare, setCompare] = useState(null)
  const [err, setErr] = useState(null)

  const load = useCallback(async () => {
    if (!playerId) return
    try {
      setP(await api.player(playerId))
      if (me?.id && me.id !== playerId) setCompare(me.style?.vector || null)
      else setCompare(null)
    } catch (e) { setErr(e.message) }
  }, [playerId, me?.id])
  useEffect(() => { load() }, [load])

  if (err) return <div className="page"><div className="banner bad">{err}</div></div>
  if (!p) return <div className="page"><div className="empty">불러오는 중…</div></div>

  const total = (p.wins || 0) + (p.losses || 0)
  const c = p.career?.counts || {}

  return (
    <div className="page">
      <button className="btn sm ghost" style={{ alignSelf: 'flex-start' }} onClick={() => history.back()}>
        ← 뒤로
      </button>

      <div className="card">
        <div className="row">
          <div>
            <div className="big">{p.name}</div>
            <div className="small muted">{p.homeCourt || '홈 코트 미설정'} · {p.handed === 'left' ? '왼손' : '오른손'}
              {p.backhand === 'one' ? ' · 원핸드 백핸드' : ' · 투핸드 백핸드'}</div>
            <div className="row wrap" style={{ marginTop: 6, gap: 6 }}>
              <span className="pill accent">NTRP {p.ntrp}</span>
              <span className="pill">{p.rating} ± {Math.round(p.rd)}</span>
              <span className="pill">{p.ratingConfidence}</span>
            </div>
          </div>
          <span className="spacer" />
          <Donut value={total ? p.wins / total : 0} label="승률" sub={`${p.wins}승 ${p.losses}패`} />
        </div>
        {p.bio && <p className="small muted" style={{ marginTop: 8 }}>{p.bio}</p>}
      </div>

      <div className="card">
        <h3>플레이스타일</h3>
        <div className="row" style={{ justifyContent: 'center' }}>
          <Radar vector={p.style?.vector || {}} labels={AXIS_KO} compare={compare} size={270} />
        </div>
        {compare && (
          <div className="legend" style={{ justifyContent: 'center' }}>
            <span><i style={{ background: '#d6f24a' }} />{p.name}</span>
            <span><i style={{ background: '#38bdf8' }} />{me.name}(나)</span>
          </div>
        )}
        <div className="row wrap" style={{ justifyContent: 'center', gap: 6, marginTop: 8 }}>
          <span className="pill accent">{p.style?.archetypeKo || '분석 전'}</span>
          {(p.style?.tags || []).map((t) => <span key={t} className="pill">{t}</span>)}
        </div>
      </div>

      {(p.career?.strengths?.length || p.career?.weaknesses?.length) ? (
        <div className="card">
          <h3>커리어 강점 / 보완점 ({p.career.matches}경기)</h3>
          <div className="list">
            {p.career.strengths.map((s) => (
              <div key={s.key} className="row">
                <span className="pill good">강점</span>
                <span style={{ flex: 1 }}>{s.label}</span>
                <span className="mono">{s.display}</span>
              </div>
            ))}
            {p.career.weaknesses.map((s) => (
              <div key={s.key} className="card tight">
                <div className="row">
                  <span className="pill bad">보완</span>
                  <span style={{ flex: 1 }}>{s.label}</span>
                  <span className="mono">{s.display}</span>
                </div>
                {s.drill && <div className="small muted" style={{ marginTop: 5 }}>🎯 {s.drill}</div>}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {Object.keys(c).length > 0 && (
        <div className="card">
          <h3>누적 기록</h3>
          <BarList items={[
            { label: '위너', value: c.winners || 0 },
            { label: '언포스드 에러', value: c.unforcedErrors || 0, color: '#fb7185' },
            { label: '에이스', value: c.aces || 0, color: '#4ade80' },
            { label: '더블폴트', value: c.doubleFaults || 0, color: '#fbbf24' },
            { label: '네트 포인트', value: c.netPoints || 0 },
          ]} />
        </div>
      )}

      {(p.topHighlights || []).length > 0 && (
        <div className="card">
          <h3>하이라이트</h3>
          <div className="list">
            {p.topHighlights.map((h) => (
              <button key={h.id} className="item" onClick={() => navigate(`report/${h.matchId}`)}>
                <div style={{ flex: 1 }}>
                  <div className="title">{h.title}</div>
                  <div className="sub">{h.caption}</div>
                </div>
                <span className="pill">{Math.round(h.score * 100)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <h3>최근 경기</h3>
        <div className="list">
          {(p.recentMatches || []).map((m) => (
            <button key={m.id} className="item" onClick={() => navigate(`report/${m.id}`)}>
              <div style={{ flex: 1 }}>
                <div className="title">{m.near.name} vs {m.far.name}</div>
                <div className="sub">{m.score || '—'} · {m.playedAt?.slice(0, 10)}</div>
              </div>
              {m.winnerId === p.id && <span className="pill good">승</span>}
              {m.winnerId && m.winnerId !== p.id && <span className="pill bad">패</span>}
            </button>
          ))}
          {(p.recentMatches || []).length === 0 && <div className="empty">기록 없음</div>}
        </div>
      </div>
    </div>
  )
}
