export function mapState(snapshot) {
  if (snapshot.stopping) return { word: 'Stopping', tone: 'danger' };
  const status = String(snapshot.status || '');
  if (!snapshot.running) {
    if (snapshot.last_run?.completed) return { word: 'Complete', tone: 'good' };
    if (/^Stopped(?::|$)/i.test(status)) return { word: 'Stopped', tone: 'muted' };
    return { word: 'Ready', tone: 'muted' };
  }
  if (/^paused/i.test(status)) return { word: 'Paused', tone: 'warn' };
  if (/respawn/i.test(status)) return { word: 'Respawning', tone: 'warn' };
  if (/^getting ready/i.test(status)) return { word: 'Preparing', tone: 'text' };
  if (/gravity/i.test(status)) return { word: 'Setting gravity', tone: 'text' };
  if (/^eating a senzu/i.test(status)) return { word: 'Eating', tone: 'good' };
  if (/^getting a senzu/i.test(status)) return { word: 'Refilling', tone: 'text' };
  if (/^training/i.test(status)) return { word: 'Training', tone: 'accent' };
  return { word: 'Running', tone: 'accent' };
}

export function clockTime(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '--:--';
  const s = Math.max(0, Math.floor(seconds));
  return [Math.floor(s / 3600), Math.floor(s % 3600 / 60), s % 60].map(n => String(n).padStart(2, '0')).join(':');
}

export function ringState(snapshot) {
  const seconds = snapshot.stats?.elapsed;
  const known = typeof seconds === 'number' && Number.isFinite(seconds) && seconds >= 0;
  const limit = snapshot.settings?.stop_after_minutes * 60;
  return {
    fraction: known && limit > 0 ? Math.min(1, seconds / limit) : 0,
    empty: !known || !(limit > 0),
    tone: known && limit > 0 && seconds >= limit ? 'power' : 'accent',
    time: known ? clockTime(seconds) : '--',
    description: known ? `Run time: ${clockTime(seconds)}${limit > 0 ? ` of ${clockTime(limit)}` : ''}` : 'Run time unavailable',
  };
}

const COUNTERS = [['elapsed', 'Run time'], ['level', 'Level'], ['senzus', 'Senzus eaten'], ['deaths', 'Deaths'], ['points_left', 'Health points left'], ['gravity', 'Gravity']];
export function statTiles(stats) {
  const source = stats && typeof stats === 'object' ? stats : {};
  return COUNTERS.map(([key, label]) => {
    const number = source[key];
    const valid = typeof number === 'number' && Number.isFinite(number) && number >= 0;
    const multiplier = typeof source.exp_mult === 'number' && Number.isFinite(source.exp_mult) && source.exp_mult > 0 ? `x${Math.round(source.exp_mult).toLocaleString('en-GB')}` : '--';
    const value = !valid ? '--' : key === 'elapsed' ? clockTime(number) : key === 'gravity' ? `${Math.floor(number)}G  ${multiplier}` : Math.floor(number).toLocaleString('en-GB');
    const hint = key === 'gravity' ? 'EXP multiplier' : key === 'level' && Number.isFinite(source.xp_percent) && source.xp_percent >= 0 ? `${Math.min(100, source.xp_percent)}% to next` : '';
    return { key, label, value, hint };
  });
}

export function runChips(settings) {
  const chips = ['Health', settings.gravity_mode === 'custom' ? `${settings.gravity}G` : 'Max gravity'];
  if (settings.auto_senzu) chips.push(`Senzu at ${settings.senzu_at}% HP`);
  if (settings.stop_after_minutes > 0) chips.push(`Stop after ${settings.stop_after_minutes} min`);
  if (settings.stop_at_level > 0) chips.push(`Stop at level ${settings.stop_at_level}`);
  return chips;
}
