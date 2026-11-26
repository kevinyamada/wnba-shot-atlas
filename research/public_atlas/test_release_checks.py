"""Regression checks for failures that must stop a release."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

import recount
import score_future


class ReleaseChecks(unittest.TestCase):
    def test_pin_mismatch_stops_before_recount(self):
        with TemporaryDirectory() as tmp, patch.object(recount, 'OUT', Path(tmp)), patch('sys.argv', ['recount']), \
                patch.object(recount, 'check_pins', return_value=(1, ['changed.csv'])), patch.object(recount, 'recount') as run:
            with self.assertRaisesRegex(SystemExit, 'changed.csv'):
                recount.main()
            run.assert_not_called()
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_comparison_failure_preserves_previous_release(self):
        changes = pd.DataFrame([{'check': 'shot count', 'difference': 1}])
        with TemporaryDirectory() as tmp, patch.object(recount, 'OUT', Path(tmp)), patch('sys.argv', ['recount']), \
                patch.object(recount, 'check_pins', return_value=(1, [])), patch.object(recount, 'recount', return_value=[None]*6), \
                patch.object(recount, 'compare', return_value=changes):
            previous = Path(tmp) / 'season_recount.csv'
            previous.write_text('previous')
            with self.assertRaisesRegex(SystemExit, 'shot count'):
                recount.main()
            self.assertEqual(previous.read_text(), 'previous')

    def test_first_prospective_score_survives_second_writer(self):
        table = pd.DataFrame([{'attempts': 12}])
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'season_2027'
            score_future.publish_once(destination, table, {'original': True})
            with self.assertRaises(SystemExit):
                score_future.publish_once(destination, table * 2, {'original': False})
            self.assertEqual(json.loads((destination / 'scores.json').read_bytes()), {'original': True})
            self.assertEqual(pd.read_csv(destination / 'scores.csv').attempts.item(), 12)

    def test_issued_forecast_files_match_registration(self):
        registered = json.loads((score_future.OUT / 'model_registration.json').read_bytes())
        for name, expected in registered['issuedForecastsSha256'].items():
            raw = (score_future.RESULTS / 'prediction_2027' / name).read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected, name)

    def test_future_inputs_required(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources = [r for r in json.loads(score_future.PIN.read_bytes()) if r['season'] <= 2026]
            pins = root / 'pins.json'
            pins.write_text(json.dumps(sources))
            (root / 'model_registration.json').write_bytes((score_future.OUT / 'model_registration.json').read_bytes())
            with patch('sys.argv', ['score_future', '--season', '2027']), patch.object(score_future, 'OUT', root), \
                    patch.object(score_future, 'PIN', pins), patch.object(score_future.joblib, 'load') as load:
                with self.assertRaisesRegex(SystemExit, 'Pin and build'):
                    score_future.main()
                load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
