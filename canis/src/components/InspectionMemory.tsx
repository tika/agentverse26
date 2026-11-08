import { useMemo, useState } from 'react';
import { useConsole, useConsoleState } from '../state/context';
import { EMPTY_FILTER, filterDrums, packageStatuses, statusOf, type Coverage, type DrumFilter, type FindingFlag } from '../lib/inspection';
import { LedgerLoader } from './LedgerLoader';
import { Panel } from './common';

const COVERAGE_LABEL: Record<Coverage, string> = {
  unseen: '○ UNSEEN',
  seen: '◐ SEEN',
  inspected: '✓ INSPECTED',
};
const FINDING_LABEL: Record<FindingFlag, string> = {
  none: '',
  observation_only: 'observation',
  inconclusive: '? inconclusive',
  finding: '▲ finding',
};

export function InspectionMemory({ compact }: { compact?: boolean }) {
  const { map, selectDrum, selectedDrumId, selectedRackId, selectRack } = useConsole();
  const state = useConsoleState();
  const [filter, setFilter] = useState<DrumFilter>(EMPTY_FILTER);
  const states = useMemo(() => packageStatuses(state), [state.inspections, state.findings]); // eslint-disable-line react-hooks/exhaustive-deps
  const effective = { ...filter, rack: filter.rack || selectedRackId || '' };
  const rows = filterDrums(map.drums, effective, states);
  const counts = { inspected: [...states.values()].filter((v) => v.coverage === 'inspected').length, seen: [...states.values()].filter((v) => v.coverage === 'seen').length };
  const set = (patch: Partial<DrumFilter>) => setFilter({ ...filter, ...patch });

  return (
    <Panel title="Inspection memory" id="inspection" className={`inspection-panel ${compact ? 'compact' : ''}`}
      right={<span className="num dim" data-testid="inventory-count">{map.drums.length} drums · {counts.inspected} inspected · {counts.seen} seen</span>}>
      <div className="filters" role="search">
        <input type="search" placeholder="Search D123 or A-L-01-T1" value={filter.query} aria-label="Search by drum ID or printed location code"
          onChange={(e) => set({ query: e.target.value })} />
        <select aria-label="Waste class" value={filter.category} onChange={(e) => set({ category: e.target.value as DrumFilter['category'] })}>
          <option value="">LLW + ILW</option><option value="LLW">LLW</option><option value="ILW">ILW</option>
        </select>
        {!compact && (
          <select aria-label="Rack" value={effective.rack} onChange={(e) => { set({ rack: e.target.value }); selectRack(e.target.value || null); }}>
            <option value="">All racks</option>
            {map.racks.map((r) => <option key={r.id} value={r.id}>{r.id} · {r.category}</option>)}
          </select>
        )}
        <select aria-label="Tier" value={filter.tier} onChange={(e) => set({ tier: e.target.value as DrumFilter['tier'] })}>
          <option value="">All tiers</option><option value="1">T1</option><option value="2">T2</option><option value="3">T3</option>
        </select>
        <select aria-label="Coverage" value={filter.coverage} onChange={(e) => set({ coverage: e.target.value as DrumFilter['coverage'] })}>
          <option value="">Any coverage</option>
          {(Object.keys(COVERAGE_LABEL) as Coverage[]).map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {!compact && (
          <select aria-label="Finding" value={filter.finding} onChange={(e) => set({ finding: e.target.value as DrumFilter['finding'] })}>
            <option value="">Any finding</option><option value="observation_only">observation</option>
            <option value="inconclusive">inconclusive</option><option value="finding">finding</option>
          </select>
        )}
        {selectedRackId && <button className="chip-btn" onClick={() => { selectRack(null); set({ rack: '' }); }}>Rack {selectedRackId} ✕</button>}
        <span className="num dim" data-testid="row-count">{rows.length} shown</span>
      </div>
      {!compact && <LedgerLoader />}
      <div className="table-scroll">
        <table className="drum-table" data-testid="drum-table">
          <thead>
            <tr><th>Drum</th><th>Printed code</th><th>Class</th><th>Rack</th><th>Tier</th>{!compact && <><th>Aisle</th><th>Position (m)</th></>}<th>Coverage</th>{!compact && <th>Finding</th>}</tr>
          </thead>
          <tbody>
            {rows.map((d) => {
              const st = statusOf(states, d);
              return (
                <tr key={d.id} className={selectedDrumId === d.id ? 'row-selected' : ''} onClick={() => selectDrum(d.id)}
                  tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') selectDrum(d.id); }} aria-label={`${d.id} ${d.location_code}`}>
                  <td className="mono">{d.id}</td>
                  <td className="mono">{d.location_code}</td>
                  <td><span className={`cat cat-${d.category}`}>{d.category}</span></td>
                  <td className="mono">{d.stack_id}</td>
                  <td className="num">T{d.tier}</td>
                  {!compact && <><td className="num">{d.facing_aisle}</td><td className="num">{d.x_m.toFixed(2)}, {d.y_m.toFixed(2)}</td></>}
                  <td className={`ist ist-${st.coverage}`} title={st.views.length ? `views: ${st.views.join(', ')}` : 'no accepted ledger records'}>{COVERAGE_LABEL[st.coverage]}</td>
                  {!compact && <td className={`ist ist-${st.finding}`}>{FINDING_LABEL[st.finding]}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
