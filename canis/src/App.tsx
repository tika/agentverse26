import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PublicDrum, PublicMap } from './contracts/publicMap';
import { ConsoleStore } from './state/store';
import { FeedBus } from './ingest/FeedBus';
import { ConsoleContext, type ConsoleContextValue, type ReplayControls, type TabId } from './state/context';
import type { Mode } from './state/types';
import { StaticAdapter } from './adapters/StaticAdapter';
import { ReplayAdapter } from './adapters/ReplayAdapter';
import { LiveAdapter, parseFeedConfig } from './adapters/LiveAdapter';
import type { Adapter } from './adapters/types';
import { Header, OfflineBanner, ReplayBanner, TABS } from './components/Header';
import { DrumDetail } from './components/DrumDetail';
import { AlertsTab, InspectionTab, LogsTab, SensorsTab, SimulationTab } from './tabs/Tabs';

const MAP_URL = '/data/warehouse-map.public.json';

function initialMode(): Mode {
  const m = new URLSearchParams(window.location.search).get('mode');
  return m === 'replay' || m === 'live' ? m : 'offline';
}

function initialTab(): TabId {
  const t = new URLSearchParams(window.location.search).get('tab');
  return (TABS.find((x) => x.id === t)?.id ?? 'simulation');
}

export default function App() {
  const [map, setMap] = useState<PublicMap | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(MAP_URL)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((m: PublicMap) => setMap(m))
      .catch((e: Error) => setError(`Could not load ${MAP_URL}: ${e.message}. Run "npm run public-map".`));
  }, []);

  if (error) return <div className="fatal" role="alert">{error}</div>;
  if (!map) return <div className="loading">Loading public warehouse map…</div>;
  return <Console map={map} />;
}

function Console({ map }: { map: PublicMap }) {
  const store = useMemo(() => new ConsoleStore(initialMode()), []);
  const bus = useMemo(() => new FeedBus(store), [store]);
  const adapter = useRef<Adapter | null>(null);
  const [replay, setReplay] = useState<ReplayControls | undefined>();
  const [tab, setTab] = useState<TabId>(initialTab);
  const [selectedDrumId, selectDrum] = useState<string | null>(null);
  const [selectedRackId, selectRack] = useState<string | null>(null);

  const drumByCode = useMemo(() => new Map<string, PublicDrum>(map.drums.map((d) => [d.location_code, d])), [map]);

  const start = useCallback((mode: Mode) => {
    adapter.current?.stop();
    const previous = store.getState().mode;
    store.reset(mode);
    bus.resetSequences();
    if (previous !== mode) store.log('info', 'mode', 'operator', `Mode changed: ${previous} → ${mode}`, mode === 'replay');
    const ctx = { store, bus, map };
    let next: Adapter;
    if (mode === 'replay') {
      // ?tick=<ms> speeds up the replay for tests and screenshots; default 1 replay-second per second.
      const tick = Number(new URLSearchParams(window.location.search).get('tick'));
      // ?at=<s> pauses the replay at that replay time.
      const atParam = new URLSearchParams(window.location.search).get('at');
      const r = new ReplayAdapter(Number.isFinite(tick) && tick >= 20 ? tick : 1000, atParam !== null && Number.isFinite(Number(atParam)) ? Number(atParam) : undefined);
      next = r;
      setReplay({ pause: () => r.pause(), resume: () => r.resume(), reset: () => r.reset() });
    } else {
      setReplay(undefined);
      next = mode === 'live'
        ? new LiveAdapter({ ...parseFeedConfig(import.meta.env.VITE_CANIS_FEEDS), ...parseFeedConfig(new URLSearchParams(window.location.search).get('feeds')) })
        : new StaticAdapter();
    }
    adapter.current = next;
    next.start(ctx);
    const url = new URL(window.location.href);
    if (mode === 'offline') url.searchParams.delete('mode'); else url.searchParams.set('mode', mode);
    window.history.replaceState(null, '', url);
  }, [store, bus, map]);

  useEffect(() => {
    start(store.getState().mode);
    return () => adapter.current?.stop();
  }, [start, store]);

  // Live mode has no replay clock driving staleness; re-evaluate once a second.
  useEffect(() => {
    const id = setInterval(() => { if (store.getState().mode === 'live') store.evaluateStaleness(); }, 1000);
    return () => clearInterval(id);
  }, [store]);

  const selectPackage = useCallback((code: string | null | undefined) => {
    if (!code) return selectDrum(null);
    const d = drumByCode.get(code) ?? map.drums.find((x) => x.id === code);
    selectDrum(d ? d.id : null);
  }, [drumByCode, map]);

  const openTab = useCallback((t: TabId) => {
    setTab(t);
    const url = new URL(window.location.href);
    if (t === 'simulation') url.searchParams.delete('tab'); else url.searchParams.set('tab', t);
    window.history.replaceState(null, '', url);
  }, []);

  const value: ConsoleContextValue = {
    store, bus, map, drumByCode, setMode: start, replay,
    selectedDrumId, selectDrum, selectPackage, selectedRackId, selectRack, openTab,
  };

  return (
    <ConsoleContext.Provider value={value}>
      <div className={`app ${tab === 'simulation' ? 'app-one-screen' : ''}`}>
        <Header tab={tab} onTab={openTab} />
        <ReplayBanner />
        <OfflineBanner />
        <main className="app-main" id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
          {tab === 'simulation' && <SimulationTab />}
          {tab === 'inspection' && <InspectionTab />}
          {tab === 'sensors' && <SensorsTab />}
          {tab === 'alerts' && <AlertsTab />}
          {tab === 'logs' && <LogsTab />}
        </main>
        <DrumDetail />
        <footer className="app-foot faint">
          C.A.N.I.S. operator console framework · read-only · public map <span className="mono">{map.source.file}</span> sha256 <span className="mono">{map.source.sha256.slice(0, 12)}</span> · baseline <span className="mono">{map.source.baseline_revision.slice(0, 7)}</span>
        </footer>
      </div>
    </ConsoleContext.Provider>
  );
}
