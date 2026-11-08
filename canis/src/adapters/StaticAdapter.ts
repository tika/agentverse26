import { FEED_IDS } from '../state/types';
import type { Adapter, AdapterContext } from './types';

/** Default mode. Public map and stills only; every live feed is reported as not configured. */
export class StaticAdapter implements Adapter {
  readonly mode = 'offline' as const;

  start({ store, map }: AdapterContext) {
    const llw = map.drums.filter((d) => d.category === 'LLW').length;
    store.log('info', 'map', 'static',
      `Public map loaded from ${map.source.file} (sha256 ${map.source.sha256.slice(0, 12)}…): ${map.drums.length} drums (${llw} LLW / ${map.drums.length - llw} ILW), ${map.racks.length} racks, hall ${map.hall_m.x} × ${map.hall_m.y} m`);
    FEED_IDS.forEach((id) => {
      store.setFeed(id, 'not_configured', 'Framework offline: no source configured');
    });
    store.log('info', 'feed', 'static', 'Framework offline: Isaac, mission, robot, sensor, detector and assessment feeds are not configured');
  }

  stop() {}
}
