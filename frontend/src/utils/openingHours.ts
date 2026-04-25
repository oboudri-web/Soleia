/**
 * Soleia - Opening hours helpers.
 *
 * Traduit les descriptions d'horaires Google Places en français et calcule
 * si un établissement est ouvert à un instant donné.
 */

export type OpeningPeriod = {
  open?: { day?: number; hour?: number; minute?: number };
  close?: { day?: number; hour?: number; minute?: number };
};

export type OpeningHours = {
  open_now?: boolean;
  periods?: OpeningPeriod[];
  weekday_descriptions?: string[];
};

const DAY_MAP: Record<string, string> = {
  Monday: 'Lundi',
  Tuesday: 'Mardi',
  Wednesday: 'Mercredi',
  Thursday: 'Jeudi',
  Friday: 'Vendredi',
  Saturday: 'Samedi',
  Sunday: 'Dimanche',
};

const STATUS_MAP: Array<[RegExp, string]> = [
  [/\bOpen 24 hours\b/gi, 'Ouvert 24h/24'],
  [/\bClosed\b/gi, 'Fermé'],
  [/\bOpen\b/gi, 'Ouvert'],
];

/**
 * Traduit un libellé "Monday: 12:00 – 14:30, 19:00 – 22:30" en français.
 * Remplace aussi les statuts Open / Closed / Open 24 hours.
 */
export function translateWeekdayDescription(str: string | null | undefined): string {
  if (!str) return '';
  let out = str;
  for (const [en, fr] of Object.entries(DAY_MAP)) {
    out = out.replace(new RegExp(`\\b${en}\\b`, 'g'), fr);
  }
  for (const [re, fr] of STATUS_MAP) {
    out = out.replace(re, fr);
  }
  // Normalise les tirets moyens/longs
  out = out.replace(/\s[–—-]\s/g, ' – ');
  return out;
}

/**
 * Google Places renvoie day=0 pour Dimanche.
 * Retourne le jour (0=Dimanche..6=Samedi) correspondant à la Date locale passée.
 */
function googleDayOf(d: Date): number {
  return d.getDay(); // JS: 0=Sunday, matches Google convention
}

function toMinutes(h?: number, m?: number): number | null {
  if (typeof h !== 'number') return null;
  return h * 60 + (m ?? 0);
}

/**
 * Détermine si l'établissement est ouvert à un instant donné.
 * Retourne :
 *   - true  : ouvert
 *   - false : fermé
 *   - null  : horaire inconnu ou ambigu (UI doit ignorer, ne pas badger "fermé")
 *
 * Supporte les périodes qui traversent minuit (close.day > open.day).
 * Ignore gracieusement les horaires 24/7 (open.day=0 h=0 m=0, close absent).
 */
export function isOpenAt(hours: OpeningHours | null | undefined, at: Date): boolean | null {
  if (!hours) return null;
  const periods = hours.periods;
  if (!Array.isArray(periods) || periods.length === 0) {
    // Pas de periods structurées → inconnu (on évite de badger "fermé" à tort)
    return null;
  }

  // Cas 24/7 : une seule période avec open.day=0 h=0 m=0 et pas de close
  if (periods.length === 1) {
    const p = periods[0];
    if (p.open && (p.open.hour ?? 0) === 0 && (p.open.minute ?? 0) === 0 && !p.close) {
      return true;
    }
  }

  const day = googleDayOf(at);            // 0..6
  const nowMin = at.getHours() * 60 + at.getMinutes();

  for (const p of periods) {
    const od = p.open?.day;
    const cd = p.close?.day;
    const om = toMinutes(p.open?.hour, p.open?.minute);
    const cm = toMinutes(p.close?.hour, p.close?.minute);
    if (od === undefined || om === null) continue;

    // Période 24/7 encodée avec close absent
    if (cd === undefined || cm === null) {
      if (od === day && nowMin >= om) return true;
      continue;
    }

    // Même jour, pas de passage minuit
    if (od === cd) {
      if (day === od && nowMin >= om && nowMin < cm) return true;
      continue;
    }

    // Passage de minuit : open day d, close day d+1 (mod 7)
    // - "now" dans la plage open.day entre om et minuit
    if (day === od && nowMin >= om) return true;
    // - "now" dans la plage close.day avant cm
    if (day === cd && nowMin < cm) return true;
  }
  return false;
}
