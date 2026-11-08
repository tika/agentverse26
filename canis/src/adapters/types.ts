import type { FeedBus } from '../ingest/FeedBus';
import type { ConsoleStore } from '../state/store';
import type { PublicMap } from '../contracts/publicMap';

export interface AdapterContext {
  store: ConsoleStore;
  bus: FeedBus;
  map: PublicMap;
}

/** Adapters only receive. None of them sends commands to the simulator or robot. */
export interface Adapter {
  readonly mode: 'offline' | 'replay' | 'live';
  start(ctx: AdapterContext): void;
  stop(): void;
}
