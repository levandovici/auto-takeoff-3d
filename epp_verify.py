from calculator import RoofCalculator, RoofConfig, RoofInput

for h in [15.0, 20.0, 25.0]:
    c = RoofConfig(thermal_slab_height_cm=h)
    q = RoofCalculator.calculate(RoofInput(20, 8, 0.4, 0.2), c)
    print(h, q.s_bitum_base_epp)
