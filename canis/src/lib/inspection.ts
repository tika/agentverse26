import type { PublicDrum } from '../contracts/publicMap';
import type { ConsoleState } from '../state/types';

/** Same rule as WarehouseObservations.coverage(): both "front" and "oblique" views → inspected. */
export type Coverage = 'unseen' | 'seen' | 'inspected';
export type FindingFlag = 'none' | 'observation_only' | 'inconclusive' | 'finding';

export const REQUIRED_VIEWS = ['front', 'oblique'] as const;

export interface PackageStatus {
  coverage: Coverage;
  views: string[];
  frames: number;
  finding: FindingFlag;
}

const UNSEEN: PackageStatus = { coverage: 'unseen', views: [], frames: 0, finding: 'none' };

/** Derived only from inspection records and findings, keyed by printed package code. Never from simulator truth. */
export function packageStatuses(state: ConsoleState): Map<string, PackageStatus> {
  const views = new Map<string, Set<string>>();
  const frames = new Map<string, Set<string>>();
  for (const r of state.inspections) {
    if (r.late) continue;
    const id = r.msg.package_id;
    if (!views.has(id)) { views.set(id, new Set()); frames.set(id, new Set()); }
    views.get(id)!.add(r.msg.view);
    frames.get(id)!.add(r.msg.frame_id);
  }
  const out = new Map<string, PackageStatus>();
  for (const [id, v] of views) {
    const coverage: Coverage = REQUIRED_VIEWS.every((x) => v.has(x)) ? 'inspected' : 'seen';
    out.set(id, { coverage, views: [...v].sort(), frames: frames.get(id)!.size, finding: 'none' });
  }
  const rank: Record<FindingFlag, number> = { none: 0, observation_only: 1, inconclusive: 2, finding: 3 };
  for (const f of state.findings) {
    if (f.late || !f.msg.package_id) continue;
    const prev = out.get(f.msg.package_id) ?? { ...UNSEEN };
    if (rank[f.msg.status] > rank[prev.finding]) prev.finding = f.msg.status;
    out.set(f.msg.package_id, prev);
  }
  return out;
}

export function statusOf(map: Map<string, PackageStatus>, d: PublicDrum): PackageStatus {
  return map.get(d.location_code) ?? UNSEEN;
}

export interface DrumFilter {
  query: string;
  category: '' | 'LLW' | 'ILW';
  rack: string;
  tier: '' | '1' | '2' | '3';
  coverage: '' | Coverage;
  finding: '' | Exclude<FindingFlag, 'none'>;
}

export const EMPTY_FILTER: DrumFilter = { query: '', category: '', rack: '', tier: '', coverage: '', finding: '' };

/** Matches canonical IDs (D7, D07, d007) and printed location codes (A-L-01-T1, a-l-01). */
export function matchesQuery(d: PublicDrum, query: string): boolean {
  const q = query.trim().toUpperCase();
  if (!q) return true;
  const idNum = /^D?0*(\d+)$/.exec(q);
  if (idNum) {
    if (Number(d.id.slice(1)) === Number(idNum[1])) return true;
    if (!q.startsWith('D')) return false;
  }
  return d.id.toUpperCase().includes(q) || d.location_code.toUpperCase().includes(q);
}

export function filterDrums(drums: PublicDrum[], f: DrumFilter, statuses: Map<string, PackageStatus>): PublicDrum[] {
  return drums.filter((d) => {
    const st = statusOf(statuses, d);
    return matchesQuery(d, f.query)
      && (!f.category || d.category === f.category)
      && (!f.rack || d.stack_id === f.rack)
      && (!f.tier || d.tier === Number(f.tier))
      && (!f.coverage || st.coverage === f.coverage)
      && (!f.finding || st.finding === f.finding);
  });
}
