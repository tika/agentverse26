"""Deterministic TWO-CUE screening, not gas detection or pressure measurement.

Inputs must come from runtime geometry and drum-surface thermal observations.
Ambient temperature is only a reference, never a substitute for a surface reading.
Thresholds are hackathon choices, not material/operational safety limits.
"""
import math
import statistics
from sensors import load_config


def screen_pressure_risk(*,bulge_pct,surface_temperatures_c,ambient_c,lid_rise_mm=0,config=None):
    cfg=(config or load_config())['pressure_screen']
    values=[bulge_pct,ambient_c,lid_rise_mm,*surface_temperatures_c]
    if not surface_temperatures_c or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):
        return {'status':'insufficient_data','action':'hold_and_remeasure','gas_confirmed':False}
    surface=statistics.median(surface_temperatures_c[-cfg['median_window']:])
    delta=surface-ambient_c
    shape=bulge_pct>=cfg['bulge_trigger_pct'] or lid_rise_mm>=cfg['lid_rise_trigger_mm']
    heat=delta>=cfg['temperature_above_ambient_c']
    if shape and heat:status,action='suspected_pressurisation','stop_and_alert'
    elif shape:status,action='shape_anomaly','flag_structural_inspection'
    elif heat:status,action='thermal_anomaly','flag_thermal_inspection'
    else:status,action='no_two_cue_anomaly','continue_monitoring'
    return {'status':status,'action':action,'gas_confirmed':False,
            'evidence':{'diameter_increase_pct':bulge_pct,'lid_rise_mm':lid_rise_mm,
                        'median_surface_c':surface,'ambient_c':ambient_c,
                        'surface_delta_c':delta,'shape_trigger':shape,'thermal_trigger':heat},
            'limits':'A cool bulged drum can still be hazardous; neither cue identifies gas or measures pressure'}
