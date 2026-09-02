// API 클라이언트. 서버와 같은 오리진에서 서빙되거나 vite 프록시를 탄다.

const BASE = import.meta.env.VITE_API_BASE || ''

async function req(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = j.detail || JSON.stringify(j)
    } catch { /* 본문이 JSON 이 아닐 수 있다 */ }
    throw new Error(detail)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  health: () => req('/api/health'),
  courtModel: () => req('/api/court/model'),

  players: (q) => req('/api/players' + (q ? `?q=${encodeURIComponent(q)}` : '')),
  player: (id) => req(`/api/players/${id}`),
  createPlayer: (body) => req('/api/players', { method: 'POST', body: JSON.stringify(body) }),

  matches: (playerId) => req('/api/matches' + (playerId ? `?playerId=${playerId}` : '')),
  match: (id) => req(`/api/matches/${id}`),
  matchStatus: (id) => req(`/api/matches/${id}/status`),
  matchShots: (id, playerId) =>
    req(`/api/matches/${id}/shots` + (playerId ? `?playerId=${playerId}` : '')),
  overrideCall: (matchId, callId, kind, playerId) =>
    req(`/api/matches/${matchId}/calls/${callId}/override?kind=${kind}` +
      (playerId ? `&playerId=${playerId}` : ''), { method: 'POST' }),
  uploadMatch: (formData) => req('/api/matches/upload', { method: 'POST', body: formData }),
  manualMatch: (body) => req('/api/matches/manual', { method: 'POST', body: JSON.stringify(body) }),
  videoUrl: (id) => `${BASE}/api/matches/${id}/video`,
  clipUrl: (id) => `${BASE}/api/highlights/${id}/clip`,

  calibrateManual: (imagePoints, frameSize) =>
    req('/api/calibrate/manual', {
      method: 'POST',
      body: JSON.stringify({ imagePoints, frameSize }),
    }),
  calibrateAuto: (blob) => {
    const fd = new FormData()
    fd.append('frame', blob, 'frame.jpg')
    return req('/api/calibrate/auto', { method: 'POST', body: fd })
  },

  suggestions: (playerId, style = 'balanced', limit = 10) =>
    req(`/api/matchmaking/suggestions?playerId=${playerId}&style=${style}&limit=${limit}`),
  requests: (playerId) =>
    req('/api/matchmaking/requests' + (playerId ? `?playerId=${playerId}` : '')),
  createRequest: (body) =>
    req('/api/matchmaking/requests', { method: 'POST', body: JSON.stringify(body) }),
  cancelRequest: (id) => req(`/api/matchmaking/requests/${id}`, { method: 'DELETE' }),
  runMatchmaking: () => req('/api/matchmaking/run', { method: 'POST' }),
  ladder: (limit = 50) => req(`/api/ladder?limit=${limit}`),

  leagues: () => req('/api/leagues'),
  league: (id) => req(`/api/leagues/${id}`),
  createLeague: (body) => req('/api/leagues', { method: 'POST', body: JSON.stringify(body) }),
  joinLeague: (id, playerId) =>
    req(`/api/leagues/${id}/join?playerId=${playerId}`, { method: 'POST' }),
  startLeague: (id) => req(`/api/leagues/${id}/start`, { method: 'POST' }),
  fixtureResult: (id, body) =>
    req(`/api/fixtures/${id}/result`, { method: 'POST', body: JSON.stringify(body) }),
  ladderChallenges: (leagueId, playerId) =>
    req(`/api/leagues/${leagueId}/challenges?playerId=${playerId}`),
}

export function liveSocketUrl(sessionId) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const host = BASE ? BASE.replace(/^https?:\/\//, '') : location.host
  return `${proto}://${host}/ws/live/${sessionId}`
}
