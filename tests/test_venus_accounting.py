import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/"scripts/venus/session_analysis.py"
spec=importlib.util.spec_from_file_location("venus_pressure_accounting",path)
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)


class OfferedAccountingTests(unittest.TestCase):
    def test_cross_device_kernel_overlap_is_not_added_twice(self):
        self.assertEqual(analysis.union_ns([(0,10),(5,15),(20,25)]),20)

    def test_censored_work_and_future_offers_stay_distinct(self):
        events=[(1.,"A",0),(2.,"A",1),(3.,"A",2)]
        arrivals=[dict(session="A",seq=0),dict(session="A",seq=1)]
        completed=[dict(session="A",seq=0,result_ready_s=1.4)]
        r=analysis.accounting(events,arrivals,completed,2.75,[.5,1.])
        self.assertEqual(r["unfinished_offered"],1)
        self.assertEqual(r["future_not_offered"],1)
        self.assertEqual(r["deadlines"]["0.5"]["matured_offers"],2)
        self.assertEqual(r["deadlines"]["0.5"]["missed_including_unfinished"],1)
        self.assertEqual(r["deadlines"]["1.0"]["matured_offers"],1)
        self.assertEqual(r["deadlines"]["1.0"]["attainment"],1.)

    def test_duplicate_completion_or_early_arrival_is_rejected(self):
        a=[dict(session="A",seq=0)]
        c=[dict(session="A",seq=0,result_ready_s=1.2)]
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            analysis.accounting([(1.,"A",0)],a,c+c,2,[1])
        with self.assertRaisesRegex(ValueError,"outside"):
            analysis.accounting([(1.,"A",0)],a,[],.5,[1])


if __name__=="__main__":unittest.main()
