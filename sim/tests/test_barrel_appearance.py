"""Geometry regression checks for the reviewed hall variants, without Isaac imports."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from drums import make_inventory
from barrel_appearance import shape_spec


class ReviewedBarrelTests(unittest.TestCase):
    def test_rust_and_bulge_are_independent(self):
        entry=make_inventory()[4]
        normal=shape_spec({**entry,'faults':['corrosion']})
        bulged=shape_spec({**entry,'faults':['bulge']})
        both=shape_spec({**entry,'faults':['corrosion','bulge']})
        self.assertEqual(bulged,both)
        self.assertAlmostEqual(normal['max_radius'],.299)
        self.assertAlmostEqual(bulged['max_radius'],.31511137,places=6)
        self.assertEqual(bulged['lid_rise'],.07)
        self.assertEqual(normal['lid_rise'],0)

    def test_llw_profile_is_not_applied_to_stainless_ilw(self):
        ilw=next(e for e in make_inventory() if e['category']=='ILW')
        self.assertAlmostEqual(shape_spec(ilw)['max_radius'],.4)
        with self.assertRaises(NotImplementedError):shape_spec({**ilw,'faults':['bulge']})


if __name__=='__main__':unittest.main()
