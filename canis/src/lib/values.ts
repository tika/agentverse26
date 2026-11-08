/**
 * Display state for a single reading. Missing, invalid, stale and
 * below-detection are distinct and always rendered as words, never as 0.
 */
export type ValueState =
  | { kind: 'missing'; reason: string }
  | { kind: 'invalid'; reason: string }
  | { kind: 'below_detection'; limit: number; unit: string; stale: boolean; ageS?: number }
  | { kind: 'value'; value: number; unit: string; digits: number; stale: boolean; ageS?: number }
  | { kind: 'not_supplied'; reason: string };

export function formatValueState(v: ValueState): string {
  switch (v.kind) {
    case 'missing':
      return `UNAVAILABLE — ${v.reason}`;
    case 'invalid':
      return `INVALID — ${v.reason}`;
    case 'not_supplied':
      return `NOT SUPPLIED — ${v.reason}`;
    case 'below_detection':
      return `< ${v.limit} ${v.unit} · BELOW DETECTION`;
    case 'value':
      return `${v.value.toFixed(v.digits)} ${v.unit}`;
  }
}

export function formatAge(ageS: number | undefined): string {
  if (ageS === undefined) return '—';
  if (ageS < 1) return '<1 s';
  if (ageS < 120) return `${ageS.toFixed(0)} s`;
  return `${(ageS / 60).toFixed(1)} min`;
}

export function formatClock(s: number): string {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
  return [h, m, sec].map((n) => String(n).padStart(2, '0')).join(':');
}
