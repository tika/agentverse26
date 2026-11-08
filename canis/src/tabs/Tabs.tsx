import { Viewport } from '../components/Viewport';
import { RobotCamera } from '../components/RobotCamera';
import { FirstPerson, Thermal } from '../components/CameraPanels';
import { NavMap } from '../components/NavMap';
import { OverheadMap } from '../components/OverheadMap';
import { FeedDetails } from '../components/FeedDetails';
import { AlertStrip, SensorStrip, StatusStrip } from '../components/Strip';
import { GammaBearingPanel, SensorHistory, Sensors, SwabPanel } from '../components/Sensors';
import { InspectionMemory } from '../components/InspectionMemory';
import { Alerts, Findings } from '../components/Alerts';
import { Logs } from '../components/Logs';

/**
 * Single-screen layout (no page scroll on desktop):
 *   primary   — third-person view, centre
 *   secondary — first-person camera (left) and bird's-eye coverage map on the RTX still (right)
 *   tertiary  — apparent thermal (left, under first-person)
 *   ref       — static-reference / frame-details column beside the third-person view
 *   strip     — robot status, sensors, alerts
 * The 420-drum table lives on the Inspection tab.
 */
export function SimulationTab() {
  return (
    <div className="grid-sim">
      <div className="a-fp"><FirstPerson fit /></div>
      <div className="a-thermal"><Thermal fit /></div>
      <div className="a-viewport"><Viewport fit /></div>
      <div className="a-ref"><FeedDetails /></div>
      <div className="a-map"><OverheadMap /></div>
      <div className="a-strip">
        <div className="a-status"><StatusStrip /></div>
        <div className="a-sensors"><SensorStrip /></div>
        <div className="a-alerts"><AlertStrip /></div>
      </div>
    </div>
  );
}

export function InspectionTab() {
  return (
    <div className="grid-two">
      <InspectionMemory />
      <NavMap tall />
    </div>
  );
}

export function SensorsTab() {
  return (
    <div className="grid-two">
      <div className="stack">
        <Sensors detailed />
        <SensorHistory />
      </div>
      <div className="stack">
        <RobotCamera layout="grid" />
        <GammaBearingPanel />
        <SwabPanel />
      </div>
    </div>
  );
}

export function AlertsTab() {
  return (
    <div className="grid-two">
      <Alerts />
      <Findings />
    </div>
  );
}

export function LogsTab() {
  return <Logs />;
}
