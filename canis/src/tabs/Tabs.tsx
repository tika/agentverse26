import { Viewport } from '../components/Viewport';
import { RobotCamera } from '../components/RobotCamera';
import { NavMap } from '../components/NavMap';
import { RobotStatus } from '../components/RobotStatus';
import { GammaBearingPanel, SensorHistory, Sensors, SwabPanel } from '../components/Sensors';
import { InspectionMemory } from '../components/InspectionMemory';
import { Alerts, Findings } from '../components/Alerts';
import { Logs } from '../components/Logs';

export function SimulationTab() {
  return (
    <div className="grid-sim">
      <div className="a-viewport"><Viewport /></div>
      <div className="a-camera"><RobotCamera /></div>
      <div className="a-map"><NavMap /></div>
      <div className="a-status"><RobotStatus /></div>
      <div className="a-sensors"><Sensors /></div>
      <div className="a-inspection"><InspectionMemory compact /></div>
      <div className="a-alerts"><Alerts compact /></div>
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
