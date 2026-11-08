# Radiation retreat scenario for aisle_patrol.py: the two ILW stops of aisle A, with A-L-11-T2 planted as a
# breached high-activity drum (strength up, self-shielding mostly gone). Along the aisle the gamma field crosses
# 7.5 uSv/h near x = 2.5 m and 100 uSv/h near x = 13 m, before the first ILW stop, so the dose rule must stop the round.
#   python tools/full_hall_report/hot_hall_canis.py run scripts/hot/full_hall/brand_data.py \
#       scripts/hot/full_hall/aisle_patrol_radiation.py scripts/hot/full_hall/aisle_patrol.py
W_NAME = 'canis_radiation_retreat'
W_STOPS = [2, 3]
W_MAX_S = 120.0
W_HOT = {'drum': 'A-L-11-T2', 'strength': 1500.0, 'mu': 0.8}
