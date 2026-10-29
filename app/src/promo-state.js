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
  const ults = counter(source.ults);
  const deaths = counter(source.deaths);
  const levels = finite(source.levels) ? source.levels : start !== null && level !== null ? level - start : null;
  const xp = counter(source.xp_percent) === null ? null : Math.min(100, source.xp_percent);
  const startXp = counter(source.start_xp_percent);
  // With XP at both ends, progress counts part-levels too (11.4 instead of 11).
  const progress = levels !== null && xp !== null && startXp !== null ? levels + (xp - startXp) / 100 : levels;
  const rate = progress !== null && elapsed > 0 ? progress * 60 / elapsed : null;
  const nextLevel = rate > 0 && xp !== null ? (100 - xp) / 100 / rate * 60 : null;
  const paused = counter(source.paused);
  // Include the current life, so zero deaths is a useful ratio as well.
  const perLife = ults !== null && deaths !== null ? ults / (deaths + 1) : null;
  return {
    level: number(level),
    xp,
    cards: [
      { key: 'level-range', label: 'Level', value: `${number(start)} to ${number(level)}`, hint: 'First and latest level readings' },
      { key: 'levels', label: 'Levels gained', value: levels === null ? '--' : `${levels > 0 ? '+' : ''}${number(levels)}`, hint: levels === null ? 'Waiting for level readings' : '' },
      { key: 'level-hour', label: 'Levels / hour', value: number(rate === null ? null : rate * 60, 0), hint: rate === null ? 'Waiting for level and run time' : "At this run's pace" },
      { key: 'next-level', label: 'Next level in', value: nextLevel === null ? '--:--' : clockTime(Math.round(nextLevel)).replace(/^00:/, ''), hint: nextLevel === null ? 'Needs an XP reading' : 'Estimate from your pace' },
      { key: 'ults-per-life', label: 'Ults per life', value: number(perLife, 1), hint: 'Includes the current life' },
      { key: 'avg-life', label: 'Average life', value: elapsed > 0 && deaths !== null ? clockTime(Math.round(elapsed / (deaths + 1))).replace(/^00:/, '') : '--:--', hint: 'Run time per life' },
      { key: 'paused', label: 'Time paused', value: paused === null ? '--:--' : clockTime(paused).replace(/^00:/, ''), hint: 'Roblox not the active window' },
    ],
  };
}

// The video magnifies the last minute. The compact HUD keeps its two-hour ring.
export function chamberBar(snapshot, ring) {
  const finalMinute = !ring.empty && counter(snapshot.time_left) !== null && snapshot.time_left <= 60;
  return {
    fraction: finalMinute ? snapshot.time_left / 60 : ring.fraction,
    description: finalMinute ? `Final minute: ${snapshot.time_left} seconds left` : `Time left: ${ring.description}`,
  };
}
