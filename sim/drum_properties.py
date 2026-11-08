"""Reproducible simulator truth. Never send these profiles to the robot planner.

Values are hackathon fixtures, not material limits or validated transport/chemistry.
Sealed drums emit no gas; a bulge alone does not imply a measurable external plume.
"""
import copy
import hashlib
import math
import random

VERSION='individual_drum_v1'


def _value(entry,name,low,high):
    key=f"{VERSION}:{entry.get('scene_seed',42)}:{entry['id']}:{entry['category']}:{name}"
    seed=int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big')
    return round(random.Random(seed).uniform(low,high),6)


def assign_properties(entry):
    """Return a copy with a complete profile, preserving IDs, layout and fault labels."""
    d=copy.deepcopy(entry);faults=set(d.get('faults',[]))
    painted=d['category']=='LLW';bulged='bulge' in faults;leaking='leak' in faults
    residue='residue' in faults
    gamma=_value(d,'gamma',.75,1.35) if painted else _value(d,'gamma',16.,24.)
    rise=_value(d,'heat',11.,15.) if bulged else _value(d,'heat',.25,1.65) if painted else _value(d,'heat',.85,2.6)
    alpha_range,beta_range=((.6,1.2),(6.,14.)) if leaking else ((.08,.25),(.8,2.8)) if residue else ((.005,.06),(.04,.6))
    # Deliberately independent modalities: a visible liquid leak need not release
    # enough hydrogen to trigger the reporting floor, and methane is not a proxy for H2.
    h2=_value(d,'h2',2.,8.) if leaking and bulged else _value(d,'h2',25.,65.) if leaking else 0.
    methane=_value(d,'ch4',.2,2.) if leaking else 0.
    d['source_strength']=gamma
    d['simulation_properties']={
        'version':VERSION,'seed':int(d.get('scene_seed',42)),
        'radiation':{'gamma_at_1m_uSv_h':gamma},
        'thermal':{'peak_above_local_air_c':rise,'fill_height_fraction':_value(d,'fill_height',.32,.52)},
        'gas':{'hydrogen_ppm_at_source':h2,'methane_ppm_at_source':methane},
        'surface_sample':{'alpha_bq_cm2':_value(d,'alpha',*alpha_range),
                          'beta_gamma_bq_cm2':_value(d,'beta_gamma',*beta_range),
                          'ph':_value(d,'ph',5.2,6.4) if leaking else _value(d,'ph',4.8,6.5) if residue else _value(d,'ph',6.5,7.8),
                          'conductivity_us_cm':_value(d,'conductivity',900.,2200.) if leaking else _value(d,'conductivity',300.,1400.) if residue else _value(d,'conductivity',25.,180.),
                          'chloride_mg_m2':_value(d,'chloride',80.,200.) if leaking else _value(d,'chloride',50.,120.) if residue else _value(d,'chloride',2.,20.)},
        'structure':{'radial_swelling_fraction':_value(d,'bulge',.075,.085) if bulged else 0.,
                     'lid_rise_m':_value(d,'lid_rise',.065,.075) if bulged else 0.},
        'acoustic':{'hiss_amplitude':_value(d,'hiss',.006,.011) if leaking and bulged else 0.},
    }
    return d


def thermal_parameters(entry,overrides=None):
    thermal=entry.get('simulation_properties',{}).get('thermal',{})
    peak=(overrides or {}).get(entry['id'],thermal.get('peak_above_local_air_c',1.2 if entry['category']=='ILW' else .3))
    return float(peak),float(thermal.get('fill_height_fraction',.4))


def surface_temperature_c(entry,local_air_c,height_fraction,overrides=None):
    peak,fill=thermal_parameters(entry,overrides)
    z=max(0.,min(1.,height_fraction))
    return local_air_c+peak*(.55+.45*math.exp(-((z-fill)/.32)**2))


def gas_fixtures(drums):
    fixtures=[]
    for d in drums:
        gas=d.get('simulation_properties',{}).get('gas',{})
        h2=gas.get('hydrogen_ppm_at_source',0.);ch4=gas.get('methane_ppm_at_source',0.)
        if h2 or ch4:fixtures.append({'position_m':[d['x'],d['y'],d['height']*.6],
                                     'hydrogen_ppm':h2,'methane_ppm':ch4})
    return fixtures


def acoustic_fixtures(drums):
    fixtures=[]
    for d in drums:
        amplitude=d.get('simulation_properties',{}).get('acoustic',{}).get('hiss_amplitude',0.)
        if amplitude:fixtures.append({'kind':'hiss','position_m':[d['x'],d['y'],d['height']*.6],
                                      'time_s':0.,'duration_s':1e9,'amplitude':amplitude})
    return fixtures
