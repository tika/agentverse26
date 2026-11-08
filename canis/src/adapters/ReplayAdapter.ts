import { buildReplay, type ReplayStep } from '../fixtures/replay';
import { FEED_IDS } from '../state/types';
import type { Adapter, AdapterContext } from './types';

/** Deterministic local replay of fictional fixture data, 1 replay-second per tick. */
export class ReplayAdapter implements Adapter {
  readonly mode = 'replay' as const;
  private ctx?: AdapterContext;
  private steps: ReplayStep[] = [];
  private index = 0;
  private timer?: ReturnType<typeof setInterval>;

  /** @param pauseAtS optional replay time at which playback pauses itself (review links, screenshots). */
  constructor(private tickMs = 1000, private pauseAtS?: number) {}

  start(ctx: AdapterContext) {
    this.ctx = ctx;
    this.steps = buildReplay(ctx.map);
    ctx.store.log('info', 'replay', 'replay', `DEMO REPLAY loaded: ${this.steps.length} steps of fictional fixture data`, true);
    FEED_IDS.forEach((id) =>
      ctx.store.setFeed(id, 'connecting', 'Demo replay fixture', { fixture: true }));
    this.index = 0;
    this.resume();
  }

  /** Apply exactly one step. Public for tests and for stepping while paused. */
  step() {
    const ctx = this.ctx;
    if (!ctx || this.index >= this.steps.length) return;
    const step = this.steps[this.index];
    ctx.store.setSimClock(step.t, 'replay:isaac');
    if (step.note) ctx.store.log('info', 'replay', 'replay', `t=${step.t}s · ${step.note}`, true);
    for (const raw of step.messages) ctx.bus.ingest(raw, 'replay');
    ctx.store.evaluateStaleness();
    this.index += 1;
    if (this.pauseAtS !== undefined && step.t >= this.pauseAtS) {
      this.pauseAtS = undefined;
      this.pause();
      return;
    }
    ctx.store.setReplay({ playing: this.timer !== undefined && this.index < this.steps.length, step: this.index, total: this.steps.length });
    if (this.index >= this.steps.length) {
      this.clearTimer();
      ctx.store.setReplay({ playing: false, step: this.index, total: this.steps.length });
      ctx.store.log('info', 'replay', 'replay', 'DEMO REPLAY finished; press Reset to replay', true);
    }
  }

  pause() {
    if (!this.timer) return;
    this.clearTimer();
    this.ctx?.store.setReplay({ playing: false, step: this.index, total: this.steps.length });
    this.ctx?.store.log('info', 'replay', 'replay', `Paused at t=${this.ctx.store.getState().simClockS ?? 0}s`, true);
  }

  resume() {
    if (this.timer || !this.ctx || this.index >= this.steps.length) return;
    this.timer = setInterval(() => this.step(), this.tickMs);
    this.ctx.store.setReplay({ playing: true, step: this.index, total: this.steps.length });
    if (this.index > 0) this.ctx.store.log('info', 'replay', 'replay', `Resumed at t=${this.ctx.store.getState().simClockS ?? 0}s`, true);
    else this.step();
  }

  reset() {
    const ctx = this.ctx;
    if (!ctx) return;
    this.clearTimer();
    ctx.store.reset('replay');
    ctx.bus.resetSequences();
    ctx.store.log('info', 'replay', 'replay', 'DEMO REPLAY reset to t=0 (paused; press Resume)', true);
    this.start(ctx);
    this.pause();
  }

  stop() {
    this.clearTimer();
  }

  private clearTimer() {
    if (this.timer) clearInterval(this.timer);
    this.timer = undefined;
  }
}
