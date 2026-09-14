// ── 앱 내 알림 ──────────────────────────────────────────────────────
// 앱이 열려 있는(또는 백그라운드에 살아 있는) 동안 계획 N분 전에 알림을 띄운다.
// 서버가 없어 웹푸시는 못 쓰므로, 앱을 닫아도 확실히 받으려면 계획을 .ics 로
// 내보내 캘린더 앱에 맡기는 쪽이 낫다(calendar.js 의 VALARM).

const timers = new Map();

export const canNotify = () => typeof Notification !== "undefined";
export const notifyState = () => (canNotify() ? Notification.permission : "unsupported");

export async function requestNotifyPermission() {
  if (!canNotify()) return "unsupported";
  if (Notification.permission === "granted") return "granted";
  try {
    return await Notification.requestPermission();
  } catch {
    return "denied";
  }
}

async function show(title, body, tag) {
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg?.showNotification) {
      await reg.showNotification(title, { body, tag, icon: "./icon-180.png", badge: "./icon-180.png" });
      return;
    }
  } catch { /* 서비스워커가 없으면 아래로 */ }
  try { new Notification(title, { body, tag, icon: "./icon-180.png" }); } catch { /* 무시 */ }
}

export function clearReminders() {
  for (const t of timers.values()) clearTimeout(t);
  timers.clear();
}

/**
 * 계획에 대해 N분 전 알림을 예약한다. 이미 예약된 것은 다시 걸지 않는다.
 * @returns 예약된 개수
 */
export function scheduleReminders(items, { reminderMin = 30, now = Date.now(), horizonHours = 18 } = {}) {
  if (notifyState() !== "granted") return 0;
  const keep = new Set();
  let n = 0;

  for (const it of items) {
    const at = it.startTs - reminderMin * 60000;
    const key = `${it.id}@${at}`;
    keep.add(key);
    if (timers.has(key)) continue;
    const delay = at - now;
    if (delay <= 0 || delay > horizonHours * 3600000) continue;
    const timer = setTimeout(() => {
      show(
        `${it.act.emoji} ${it.act.name} ${reminderMin}분 전`,
        it.pred ? `예상 소모 HP ${Math.round(it.pred.hp)} · MP ${Math.round(it.pred.mp)}` : "",
        key
      );
      timers.delete(key);
    }, delay);
    timers.set(key, timer);
    n++;
  }

  for (const [key, t] of [...timers.entries()]) {
    if (!keep.has(key)) { clearTimeout(t); timers.delete(key); }
  }
  return n;
}

export const scheduledCount = () => timers.size;
