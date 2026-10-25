export function formatSeconds(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '--';
  const value = Math.max(0, Math.trunc(seconds));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor(value % 3600 / 60);
  const remainder = value % 60;
  if (hours) return `${hours}h ${minutes}m ${remainder}s`;
  if (minutes) return `${minutes}m ${remainder}s`;
  return `${remainder}s`;
}
