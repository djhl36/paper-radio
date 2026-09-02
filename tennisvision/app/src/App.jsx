import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './lib/api.js'
import Home from './pages/Home.jsx'
import Live from './pages/Live.jsx'
import Matches from './pages/Matches.jsx'
import MatchReport from './pages/MatchReport.jsx'
import Matchmaking from './pages/Matchmaking.jsx'
import Leagues from './pages/Leagues.jsx'
import Profile from './pages/Profile.jsx'

const TABS = [
  { key: 'home', label: '홈', ico: '🎾' },
  { key: 'live', label: '라이브 심판', ico: '⚖️' },
  { key: 'matches', label: '경기', ico: '📊' },
  { key: 'match', label: '매칭', ico: '🤝' },
  { key: 'leagues', label: '리그', ico: '🏆' },
]

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '')
  const [route, ...rest] = raw.split('/')
  return { route: route || 'home', params: rest }
}

export function navigate(path) {
  location.hash = '#/' + path.replace(/^\//, '')
}

export default function App() {
  const [loc, setLoc] = useState(parseHash())
  const [me, setMe] = useState(null)
  const [players, setPlayers] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    const onHash = () => setLoc(parseHash())
    addEventListener('hashchange', onHash)
    return () => removeEventListener('hashchange', onHash)
  }, [])

  const loadPlayers = useCallback(async () => {
    try {
      const list = await api.players()
      setPlayers(list)
      const savedId = Number(localStorage.getItem('tv.playerId') || 0)
      const found = list.find((p) => p.id === savedId) || list[0]
      if (found) {
        const full = await api.player(found.id)
        setMe(full)
        localStorage.setItem('tv.playerId', String(found.id))
      }
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { loadPlayers() }, [loadPlayers])

  const switchPlayer = useCallback(async (id) => {
    localStorage.setItem('tv.playerId', String(id))
    setMe(await api.player(id))
  }, [])

  const refreshMe = useCallback(async () => {
    if (me?.id) setMe(await api.player(me.id))
  }, [me?.id])

  const ctx = useMemo(
    () => ({ me, players, switchPlayer, refreshMe, reload: loadPlayers }),
    [me, players, switchPlayer, refreshMe, loadPlayers],
  )

  const activeTab = ['home', 'live', 'matches', 'match', 'leagues'].includes(loc.route)
    ? loc.route
    : loc.route === 'report' ? 'matches' : loc.route === 'profile' ? 'home' : 'home'

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand-dot" />
        <h1>TennisVision</h1>
        <span className="spacer" />
        {players.length > 0 && (
          <select
            value={me?.id || ''}
            onChange={(e) => switchPlayer(Number(e.target.value))}
            style={{ width: 'auto', fontSize: 13, padding: '5px 9px' }}
            aria-label="사용자 선택"
          >
            {players.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
      </header>

      {error && <div className="page"><div className="banner bad">서버 연결 실패: {error}</div></div>}

      {loc.route === 'home' && <Home ctx={ctx} />}
      {loc.route === 'live' && <Live ctx={ctx} />}
      {loc.route === 'matches' && <Matches ctx={ctx} />}
      {loc.route === 'report' && <MatchReport ctx={ctx} matchId={Number(loc.params[0])} />}
      {loc.route === 'match' && <Matchmaking ctx={ctx} />}
      {loc.route === 'leagues' && <Leagues ctx={ctx} leagueId={loc.params[0] ? Number(loc.params[0]) : null} />}
      {loc.route === 'profile' && <Profile ctx={ctx} playerId={loc.params[0] ? Number(loc.params[0]) : me?.id} />}

      <nav className="nav">
        {TABS.map((t) => (
          <button key={t.key} className={activeTab === t.key ? 'active' : ''}
            onClick={() => navigate(t.key)}>
            <span className="ico">{t.ico}</span>
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  )
}
