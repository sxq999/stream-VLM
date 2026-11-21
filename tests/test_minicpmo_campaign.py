import copy
import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / 'scripts/minicpmo/run_stress_cases.py'
spec = importlib.util.spec_from_file_location('campaign', source)
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


class CampaignContractTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'cases': [{'id': 'a', 'planned_repeats': 2, 'sessions': [{'media': 'omni1'}]},
                               {'id': 'b', 'planned_repeats': 2, 'sessions': [{'media': 'omni2'}]}],
                     'round_orders': [['a', 'b'], ['b', 'a']]}

    def test_repeated_or_missing_round_cases_are_rejected(self):
        campaign.validate_plan(self.plan)
        for order in (['a', 'a'], ['a'], ['a', 'b', 'b']):
            invalid = copy.deepcopy(self.plan)
            invalid['round_orders'][0] = order
            with self.assertRaises(ValueError):
                campaign.validate_plan(invalid)

    def test_load_case_cannot_change_engine_configuration(self):
        self.plan['cases'][0]['sessions'][0]['gpu_memory_utilization'] = .5
        with self.assertRaisesRegex(ValueError, 'inputs only'):
            campaign.validate_plan(self.plan)


if __name__ == '__main__':
    unittest.main()
