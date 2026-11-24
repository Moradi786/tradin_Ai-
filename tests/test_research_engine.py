import unittest
from research_engine import cvd, risk_levels, backtest, calibration

class ResearchTests(unittest.TestCase):
    def test_cvd(self):
        row = [0]*11
        row[7], row[10] = 100, 60
        self.assertEqual(cvd([row]), 20)
        row[10] = 101
        self.assertIsNone(cvd([row]))

    def test_risk(self):
        self.assertEqual(risk_levels(100, 2, "LONG"), (97, 106))
        self.assertEqual(risk_levels(100, 2, "SHORT"), (103, 94))

    def test_stop_first(self):
        bars = [{"open":100,"high":110,"low":90,"close":100}]*3
        result = backtest(bars, [(0,"LONG",2,80)], horizon=2)
        self.assertAlmostEqual(result[0]["net_return"], -.032)
        self.assertEqual(calibration(result), {})
