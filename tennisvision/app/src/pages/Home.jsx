import React, { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { navigate } from '../App.jsx'
import { Radar, Donut } from '../components/Charts.jsx'

const AXIS_KO = {
  aggression: '공격성', power: '파워', consistency: '안정성', net_play: '네트',
  serve: '서브', return_game: '리턴', variety: '다양성', depth: '깊이',
  movement: '활동량', forehand_bias: '포핸드',
}

export default function Home({ ctx }) {
  const { me } = ctx
  const [suggestions, setSuggestions] = useState([])
  const [highlights, setHighlights] = useState([])

  useEffect(() => {
    if (!me?.id) return
    api.suggestions(me.id, 'balanced', 3).then((r) => setSuggestions(r.candidates)).catch(() => {})
    setHighlights(me.topHighlights || [])
  }, [me?.id])

  if (!me) {
    return (
      <div className="page">
        <div className="card">
          <h2>선수 등록이 필요합니다</h2>
          <p className="muted small">
            서버에 등록된 선수가 없습니다. 데모 데이터를 넣으려면 터미널에서
            <code> python -m server.seed </code>를 실행하세요.
          </p>
        </div>
      </div>
    )
  }

  const wins = me.wins || 0
  const losses = me.losses || 0
  const total = wins + losses

  return (
    <div className="page">
      {/* 내 카드 */}
      <div className="card">
        <div className="row">
          <div>
            <div className="muted small">{me.homeCourt || '홈 코트 미설정'}</div>
            <div className="big">{me.name}</div>
            <div className="row wrap" style={{ marginTop: 6, gap: 6 }}>
              <span className="pill accent">NTRP {me.ntrp}</span>
              <span className="pill">레이팅 {me.rating} ± {Math.round(me.rd)}</span>
              <span className="pill">{me.ratingConfidence}</span>
              {me.archetype && <span className="pill">{me.archetype}</span>}
            </div>
          </div>
          <span className="spacer" />
          <Donut value={total ? wins / total : 0} label="승률" sub={`${wins}승 ${losses}패`} />
        </div>
      </div>

      {/* 바로 시작 */}
      <div className="grid2">
        <button className="btn primary" style={{ padding: '16px 10px' }} onClick={() => navigate('live')}>
          ⚖️ 라이브 심판 시작
        </button>
        <button className="btn" style={{ padding: '16px 10px' }} onClick={() => navigate('matches')}>
          📹 경기 영상 분석
        </button>
      </div>

      {/* 스타일 */}
      <div className="card">
        <h3>내 플레이스타일</h3>
        {me.style?.vector && Object.keys(me.style.vector).length ? (
          <>
            <div className="row" style={{ justifyContent: 'center' }}>
              <Radar vector={me.style.vector} labels={AXIS_KO} size={250} />
            </div>
            <div className="row wrap" style={{ justifyContent: 'center', gap: 6 }}>
              <span className="pill accent">{me.style.archetypeKo}</span>
              {(me.style.tags || []).map((t) => <span key={t} className="pill">{t}</span>)}
            </div>
            <div className="small muted center" style={{ marginTop: 8 }}>
              {me.style.matches}경기 누적 · 신뢰도 {Math.round((me.style.confidence || 0) * 100)}%
            </div>
          </>
        ) : (
          <div className="empty">경기를 분석하면 여기에 스타일이 만들어집니다.</div>
        )}
        <button className="btn ghost sm" style={{ marginTop: 10, width: '100%' }}
          onClick={() => navigate(`profile/${me.id}`)}>
          상세 프로필 보기
        </button>
      </div>

      {/* 커리어 강점/약점 */}
      {(me.career?.strengths?.length > 0 || me.career?.weaknesses?.length > 0) && (
        <div className="card">
          <h3>코치 요약 ({me.career.matches}경기 누적)</h3>
          <div className="list">
            {me.career.strengths.map((s) => (
              <div key={s.key} className="row">
                <span className="pill good">강점</span>
                <span style={{ flex: 1 }}>{s.label}</span>
                <span className="mono">{s.display}</span>
              </div>
            ))}
            {me.career.weaknesses.map((s) => (
              <div key={s.key} className="row">
                <span className="pill bad">보완</span>
                <span style={{ flex: 1 }}>{s.label}</span>
                <span className="mono">{s.display}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 추천 상대 */}
      <div className="card">
        <h3>오늘의 추천 상대</h3>
        {suggestions.length === 0 ? (
          <div className="empty">추천할 상대가 없습니다.</div>
        ) : (
          <div className="list">
            {suggestions.map((c) => (
              <button key={c.playerId} className="item" onClick={() => navigate(`profile/${c.playerId}`)}>
                <div style={{ flex: 1 }}>
                  <div className="title">{c.name} <span className="muted small">NTRP {c.ntrp}</span></div>
                  <div className="sub">{c.reasons[0] || c.predicted}</div>
                </div>
                <span className="pill accent">{Math.round(c.score * 100)}</span>
              </button>
            ))}
          </div>
        )}
        <button className="btn ghost sm" style={{ marginTop: 10, width: '100%' }}
          onClick={() => navigate('match')}>
          매칭 전체 보기
        </button>
      </div>

      {/* 하이라이트 */}
      {highlights.length > 0 && (
        <div className="card">
          <h3>내 하이라이트</h3>
          <div className="list">
            {highlights.slice(0, 5).map((h) => (
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

      {/* 최근 경기 */}
      <div className="card">
        <h3>최근 경기</h3>
        {(me.recentMatches || []).length === 0 ? (
          <div className="empty">아직 기록된 경기가 없습니다.</div>
        ) : (
          <div className="list">
            {me.recentMatches.slice(0, 5).map((m) => (
              <button key={m.id} className="item" onClick={() => navigate(`report/${m.id}`)}>
                <div style={{ flex: 1 }}>
                  <div className="title">{m.near.name} vs {m.far.name}</div>
                  <div className="sub">
                    {m.score || '기록 없음'} · {m.playedAt?.slice(0, 10)}
                  </div>
                </div>
                {m.winnerId === me.id && <span className="pill good">승</span>}
                {m.winnerId && m.winnerId !== me.id && <span className="pill bad">패</span>}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
