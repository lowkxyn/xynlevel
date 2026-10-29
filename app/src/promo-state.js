import { clockTime } from './run-state.js';

const finite = value => typeof value === 'number' && Number.isFinite(value);
const counter = value => finite(value) && value >= 0 ? value : null;
const number = (value, digits = 0) => value === null ? '--' : value.toLocaleString('en-GB', { maximumFractionDigits: digits });

// Every value comes from this run's bridge snapshot. Missing OCR is not zero.
export function sessionMetrics(stats) {
  const source = stats && typeof stats === 'object' ? stats : {};
  const start = counter(source.start_level);
  const level = counter(source.level);
  const elapsed = counter(source.elapsed);
  const deaths = counter(source.deaths);
  const levels = finite(source.levels) ? source.levels : start !== null && level !== null ? level - start : null;
  const xp = counter(source.xp_percent) === null ? null : Math.min(100, source.xp_percent);
  const startXp = counter(source.start_xp_percent);
  // With XP at both ends, progress counts part-levels too (11.4 instead of 11).
  const progress = levels !== null && xp !== null && startXp !== null ? levels + (xp - startXp) / 100 : levels;
  const rate = progress !== null && elapsed > 0 ? progress * 60 / elapsed : null;
  const nextLevel = rate > 0 && xp !== null ? (100 - xp) / 100 / rate * 60 : null;
  const paused = counter(source.paused);
  return {
    level: number(level),
    xp,
    cards: [
      { key: 'levels', label: 'Levels gained', value: levels === null ? '--' : `${levels > 0 ? '+' : ''}${number(levels)}`, hint: levels === null ? 'Waiting for level readings' : '' },
      { key: 'level-hour', label: 'Levels / hour', value: number(rate === null ? null : rate * 60, 0), hint: rate === null ? 'Waiting for level and run time' : "At this run's pace" },
      { key: 'next-level', label: 'Next level in', value: nextLevel === null ? '--' : clockTime(Math.round(nextLevel)).replace(/^00:/, ''), hint: nextLevel === null ? 'Needs an XP reading' : 'Estimate from your pace' },
      { key: 'senzus', label: 'Senzus eaten', value: number(counter(source.senzus)), hint: 'During this run' },
      { key: 'senzu-left', label: 'Senzus left', value: number(counter(source.senzu_left)), hint: 'In your inventory' },
      { key: 'deaths', label: 'Deaths', value: number(deaths), hint: '' },
      { key: 'paused', label: 'Time paused', value: paused === null ? '--' : clockTime(paused).replace(/^00:/, ''), hint: 'Roblox not the active window' },
    ],
  };
}
