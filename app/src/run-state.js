import { formatSeconds } from './format.js';

export function mapState(snapshot) {
  if (snapshot.stopping) return { word: 'Stopping', tone: 'danger' };
  const status = String(snapshot.status || '');
  if (!snapshot.running) {
    if (snapshot.last_run?.completed) return { word: 'Complete', tone: 'good' };
    if (/^Stopped:/i.test(status)) return { word: 'Stopped', tone: 'muted' };
    return { word: 'Ready', tone: 'muted' };
  }
  if (/^paused/i.test(status)) return { word: 'Paused', tone: 'warn' };
  if (/dead|respawn|loading/i.test(status)) return { word: 'Respawning', tone: 'warn' };
  if (/gravity/i.test(status)) return { word: 'Setting gravity', tone: 'text' };
  if (/shop|buy/i.test(status)) return { word: 'Shopping', tone: 'text' };
  if (/re.?lock|lock.on/i.test(status)) return { word: 'Locking', tone: 'text' };
  if (/firing|fired/i.test(status)) return { word: 'Firing', tone: 'power' };
  if (/blasts/i.test(status)) return { word: 'Blasts', tone: 'accent' };
  if (/charg/i.test(status)) return { word: 'Charging', tone: 'accent' };
  return { word: 'Running', tone: 'accent' };
}

export function clockTime(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return '--:--';
  const s = Math.max(0, Math.floor(seconds));
  return [Math.floor(s / 3600), Math.floor(s % 3600 / 60), s % 60].map(n => String(n).padStart(2, '0')).join(':');
}

export function ringState(snapshot) {
  const seconds = snapshot.time_left;
  const known = typeof seconds === 'number' && Number.isFinite(seconds);
  const active = snapshot.running || Boolean(snapshot.last_run?.completed);
  const threshold = snapshot.settings?.stop_enabled && known && seconds <= snapshot.settings.stop_at_seconds;
  return {
    fraction: known && active ? Math.min(1, Math.max(0, seconds / 7200)) : 0,
    empty: !known || !active,
    tone: threshold ? 'power' : known && seconds < 600 ? 'warn' : 'accent',
    time: known && active ? (seconds >= 3600 ? clockTime(seconds).replace(/^0/, '') : clockTime(seconds).slice(3)) : '--:--',
    description: known ? (snapshot.time_formatted || formatSeconds(seconds)) : 'Time not available',
  };
}

const COUNTERS = [['elapsed', 'Run time'], ['level', 'Level'], ['ults', 'Ults fired'], ['deaths', 'Deaths'], ['blasts', 'Ki blasts'], ['levels', 'Levels']];
export function statTiles(stats) {
  if (!stats || typeof stats !== 'object') return [];
  return COUNTERS.filter(([key]) => Object.hasOwn(stats, key)).map(([key, label]) => {
    const number = stats[key];
    const valid = typeof number === 'number' && Number.isFinite(number) && number >= 0;
    const levelHint = key === 'level' && Number.isFinite(stats.xp_percent) ? `${stats.xp_percent}% to next` : '';
    return { key, label, value: !valid ? '--' : key === 'elapsed' ? clockTime(number) : `${key === 'levels' ? '+' : ''}${Math.floor(number).toLocaleString('en-GB')}`, hint: !valid ? (key === 'levels' ? 'not tracked' : 'unavailable') : levelHint };
  });
}

export function runChips(settings) {
  const chips = [{ auto: 'Auto', blasts: 'Ki blasts', ult: `Ult · ${settings.ult_slot}` }[settings.attack]];
  if (settings.auto_gravity) chips.push(`${settings.gravity}G`);
  if (settings.movement !== 'off') chips.push({ w: 'W', wa: 'W+A', wd: 'W+D', circle: 'Circle' }[settings.movement]);
  if (settings.stop_enabled) chips.push(`Stop · ${formatSeconds(settings.stop_at_seconds)}`);
  return chips.filter(Boolean);
}
