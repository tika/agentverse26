import type { CameraId } from '../contracts/messages';
import type { StaleChannel } from '../state/types';

/**
 * Freshness windows in seconds. Measured on the source clock (t_sim_s) when the
 * message carries one, otherwise on receive time. Tune per integration.
 */
export const FRESHNESS_S: Record<'pose' | 'sensor' | 'run_state' | 'frame', number> = {
  pose: 3,
  sensor: 8,
  run_state: 10,
  frame: 5,
};

export function windowFor(channel: StaleChannel): number {
  if (channel.startsWith('frame:')) return FRESHNESS_S.frame;
  return FRESHNESS_S[channel as 'pose' | 'sensor' | 'run_state'];
}

export const frameChannel = (id: CameraId): StaleChannel => `frame:${id}`;

/**
 * Age of a sample. Prefers the source clock: a simulator can pause or run
 * faster than real time, so wall-clock age would be misleading.
 */
export function ageSeconds(
  sample: { tSimS?: number; recvMs: number },
  now: { simS?: number; wallMs: number },
): number {
  if (sample.tSimS !== undefined && now.simS !== undefined) return Math.max(0, now.simS - sample.tSimS);
  return Math.max(0, (now.wallMs - sample.recvMs) / 1000);
}
