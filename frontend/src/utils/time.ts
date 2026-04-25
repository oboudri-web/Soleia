/**
 * Soleia - Time utilities (French format)
 */

/** Format minutes (from midnight) to French "14h30" / "14h" */
export function formatTimeFr(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h${m.toString().padStart(2, '0')}`;
}

/** Parse "HH:MM" string to French "14h30" / "14h" */
export function hhmmToFr(hhmm: string): string {
  const parts = hhmm.split(':').map((s) => parseInt(s, 10));
  if (parts.length !== 2 || isNaN(parts[0])) return hhmm;
  const [h, m] = parts;
  return m === 0 ? `${h}h` : `${h}h${m.toString().padStart(2, '0')}`;
}
