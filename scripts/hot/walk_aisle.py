# Hot-worker request: walk Spot down the centre aisle past the LLW and ILW rows,
# then show three ID plates from the aisle. Edit and rerun with:
#   python tools/hot_hall.py run scripts/hot/walk_aisle.py
walk([(9.0, 6.0), (16.5, 6.0)], name='centre_aisle', max_s=30)
still((12.6, 5.6, 1.15), (14.6, 7.45, 0.6), name='row_c_plates', focal=18)
