import { FEED_IDS, type FeedId } from '../state/types';
import type { Adapter, AdapterContext } from './types';

/**
 * Future live adapter. One read-only WebSocket per feed. Each socket delivers
 * canis.v1 envelopes as JSON text, either one object or an array per frame.
 *
 * Configure with `?feeds=isaac=ws://host:8765,robot=ws://host:8766` or the
 * VITE_CANIS_FEEDS build variable (same syntax). Unconfigured feeds stay
 * "not configured". The adapter never calls `send`.
 */
export function parseFeedConfig(spec: string | undefined | null): Partial<Record<FeedId, string>> {
  const out: Partial<Record<FeedId, string>> = {};
  if (!spec) return out;
  for (const part of spec.split(',')) {
    const [id, url] = part.split('=').map((s) => s?.trim());
    if (!id || !url) continue;
    if (!(FEED_IDS as string[]).includes(id)) continue;
    if (!/^wss?:\/\//.test(url)) continue;
    out[id as FeedId] = url;
  }
  return out;
}

export class LiveAdapter implements Adapter {
  readonly mode = 'live' as const;
  private sockets = new Map<FeedId, WebSocket>();
  private retry = new Map<FeedId, ReturnType<typeof setTimeout>>();
  private stopped = false;

  constructor(private config: Partial<Record<FeedId, string>>) {}

  start(ctx: AdapterContext) {
    this.stopped = false;
    const all = FEED_IDS;
    for (const id of all) {
      const url = this.config[id];
      if (!url) ctx.store.setFeed(id, 'not_configured', 'No URL configured for this feed');
      else this.connect(ctx, id, url, 0);
    }
    if (!Object.keys(this.config).length) {
      ctx.store.log('warn', 'feed', 'live', 'Live mode selected but no feeds configured (use ?feeds=isaac=ws://…)');
    }
  }

  private connect(ctx: AdapterContext, id: FeedId, url: string, attempt: number) {
    if (this.stopped) return;
    ctx.store.setFeed(id, 'connecting', `Connecting to ${url}`);
    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
    } catch (e) {
      ctx.store.setFeed(id, 'disconnected', `Invalid URL ${url}`);
      ctx.store.log('error', 'feed', id, `Could not open ${url}: ${(e as Error).message}`);
      return;
    }
    this.sockets.set(id, socket);
    socket.onopen = () => {
      ctx.store.setFeed(id, 'connected', `Connected to ${url}`);
      ctx.store.log('info', 'feed', id, `Connected to ${url}`);
    };
    socket.onmessage = (event) => {
      let payload: unknown;
      try {
        payload = JSON.parse(String(event.data));
      } catch {
        ctx.store.log('error', 'schema', id, 'Non-JSON frame dropped');
        return;
      }
      for (const item of Array.isArray(payload) ? payload : [payload]) ctx.bus.ingest(item, id);
    };
    socket.onclose = () => {
      if (this.stopped) return;
      const delay = Math.min(30_000, 1000 * 2 ** attempt);
      ctx.store.setFeed(id, 'disconnected', `Disconnected; retrying in ${Math.round(delay / 1000)} s`);
      ctx.store.log('warn', 'feed', id, `Disconnected from ${url}; retry in ${Math.round(delay / 1000)} s`);
      this.retry.set(id, setTimeout(() => this.connect(ctx, id, url, attempt + 1), delay));
    };
  }

  stop() {
    this.stopped = true;
    this.retry.forEach((t) => clearTimeout(t));
    this.sockets.forEach((s) => s.close());
    this.sockets.clear();
  }
}
