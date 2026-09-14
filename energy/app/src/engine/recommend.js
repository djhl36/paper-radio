
/**
 * 지금 상태에서 할 만한 활동 / 피할 활동.
 * 남은 예산의 절반쯤을 쓰는 활동을 "가장 알맞은 것"으로 본다.
 * (지쳐 있으면 자연스럽게 회복형 활동이, 여유가 있으면 큰 활동이 위로 온다)
 */
export function recommend(activities, state, profile, predictFor, budget) {
  const ideal = Math.max(0, (budget.hp + budget.mp) * 0.5);
  const rows = activities.map((a) => {
    const p = predictFor(a, { durationMin: a.dur, intensity: 5 });
    const after = { hp: Math.max(0, state.hp - p.hp), mp: Math.max(0, state.mp - p.mp) };
    const margin = Math.min(after.hp, after.mp) - profile.floor;
    const cost = p.hp + p.mp;
    return { act: a, pred: p, after, margin, cost, fit: -Math.abs(cost - ideal) };
  });

  const good = rows.filter((r) => r.margin >= 0).sort((a, b) => b.fit - a.fit);
  const avoid = rows.filter((r) => r.margin < -8).sort((a, b) => a.margin - b.margin);
  return { good, avoid, ideal };
}
