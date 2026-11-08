import { createContext, useContext, useEffect, useState, useSyncExternalStore } from 'react';
import type { PublicDrum, PublicMap } from '../contracts/publicMap';
import type { ConsoleStore } from './store';
import type { FeedBus } from '../ingest/FeedBus';
import type { ConsoleState, Mode } from './types';

export interface ReplayControls {
  pause(): void;
  resume(): void;
  reset(): void;
}

export interface ConsoleContextValue {
  store: ConsoleStore;
  bus: FeedBus;
  map: PublicMap;
  /** Printed location code → drum. The observation key is the printed code. */
  drumByCode: Map<string, PublicDrum>;
  /** Select by canonical ID or printed code. */
  selectPackage(code: string | null | undefined): void;
  setMode(mode: Mode, liveFeeds?: string): void;
  replay?: ReplayControls;
  selectedDrumId: string | null;
  selectDrum(id: string | null): void;
  selectedRackId: string | null;
  selectRack(id: string | null): void;
  openTab(tab: TabId): void;
  /** Opens the Configure Simulation dialog (feeds, recorded run, ledger file). */
  openConfigure(): void;
  /** False shows the raw evidence image with no boxes or result shapes. */
  overlays: boolean;
  setOverlays(on: boolean): void;
}

export type TabId = 'simulation' | 'inspection' | 'sensors' | 'alerts' | 'logs';

export const ConsoleContext = createContext<ConsoleContextValue | null>(null);

export function useConsole(): ConsoleContextValue {
  const ctx = useContext(ConsoleContext);
  if (!ctx) throw new Error('ConsoleContext missing');
  return ctx;
}

export function useConsoleState(): ConsoleState {
  const { store } = useConsole();
  return useSyncExternalStore(store.subscribe, store.getState);
}

/** Re-render once a second so ages and freshness labels stay current. */
export function useTicker(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}
