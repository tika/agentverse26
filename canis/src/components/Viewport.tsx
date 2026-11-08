import { useConsoleState } from '../state/context';
import { Fit, Panel } from './common';
import { FrameView } from './FrameView';

const STILL = '/assets/stills/warehouse-wide-aisles-overhead.png';
/** The 1600×1000 still has light margins; the hall occupies roughly x 375–1225 px. */
const CROP_RATIO = 850 / 1000;

export function Viewport({ fit }: { fit?: boolean }) {
  const state = useConsoleState();
  const frame = state.frames.third_person;
  const feed = state.feeds.isaac;
  return (
    <Panel title="Simulation (third-person)" id="viewport" className="viewport-panel"
      right={<span className="dim">{frame ? `camera third_person · ${feed.status.toUpperCase()}` : 'no third-person feed'}</span>}>
      {frame ? (
        <FrameView frame={frame} stale={Boolean(state.stale['frame:third_person'])} fit={fit} />
      ) : (
        <div className={`static-ref ${fit ? 'static-fit' : ''}`} data-testid="static-reference">
          <figure className="frame">
            <Fit ratio={CROP_RATIO} enabled={Boolean(fit)}>
              <div className="frame-img still-crop">
                {/* Cropped with CSS to the hall region. The file itself is unmodified. */}
                <img src={STILL} alt="Isaac RTX roof-off overview of the widened 24 × 28.30 m warehouse" width={1600} height={1000} />
                <div className="static-stamp">STATIC REFERENCE · NOT LIVE</div>
              </div>
            </Fit>
          </figure>
          <div className="static-info">
            <div className="static-title">Third-person feed not connected</div>
            <dl className="kv">
              <div className="kv-row"><dt>Shown</dt><dd>Isaac Sim 6.2 RTX still, roof-off overview (wide-aisles review)</dd></div>
              <div className="kv-row"><dt>File</dt><dd className="mono">sim/warehouse-v3/review/wide-aisles/overhead.png</dd></div>
              <div className="kv-row"><dt>Hall</dt><dd className="num">24.00 × 28.30 m · 5 aisles × 3.32 m clear</dd></div>
              <div className="kv-row"><dt>Inventory</dt><dd className="num">420 drums · 336 LLW · 84 ILW</dd></div>
              <div className="kv-row"><dt>Frame ID / clock</dt><dd className="faint">none — static image</dd></div>
            </dl>
            <p className="faint small">
              When an Isaac feed connects, this panel shows timestamped <span className="mono">camera_frame</span> messages for
              <span className="mono"> camera_id: third_person</span>. Detection overlays draw only on the frame they reference.
            </p>
          </div>
        </div>
      )}
    </Panel>
  );
}
