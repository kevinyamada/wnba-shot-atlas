"""Add the shot family to the atlas's fixed context model on its original test attempts."""
import json

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.preprocessing import OneHotEncoder

from benchmark import TEST, VALIDATION
from build import DERIVED, RESULTS, write_json
from shot_form import OUT, UNKNOWN, game_totals, recorded_form, score
from shot_models import CATEGORICAL, SEEDS, dataset, make_xgboost, xgb_features

SAVED = DERIVED / 'shot_predictions.csv.gz'
OUTPUT = DERIVED / 'form_context_predictions.csv.gz'
MODEL = 'XGBoost context'


def compare():
    model_dir = RESULTS / 'shot_models'
    design = json.loads((model_dir/'design.json').read_bytes())
    assert design['selected'] == MODEL and design['validation'] == VALIDATION and design['test'] == TEST
    trials = pd.read_csv(model_dir/'validation_selection.csv')
    candidates = trials.loc[trials.model.eq(MODEL)].sort_values('validation_log_loss')
    depth = int(candidates.iloc[0].settings.removeprefix('depth='))
    data, _ = dataset()
    train = data[data.split.eq('train')]
    test = data[data.split.isin(['test','playoffs'])].copy()
    encoder = OneHotEncoder(handle_unknown='ignore').fit(train[CATEGORICAL])

    def matrices(rows):
        basic = xgb_features(rows, True, encoder)
        forms = recorded_form(rows.type_text)
        idx = np.flatnonzero(forms != UNKNOWN)
        extra = sparse.csr_matrix((np.ones(len(idx)), (idx, forms[idx])), shape=(len(rows), UNKNOWN))
        return basic, sparse.hstack((basic, extra),format='csr')

    train_x, test_x = matrices(train), matrices(test)
    for idx, name in enumerate(['baseline', 'with_form']):
        members = []
        for seed in SEEDS:
            m = make_xgboost(depth, seed)
            m.fit(train_x[idx], train.made)
            members.append(m.predict_proba(test_x[idx])[:,1])
        test[name] = np.mean(members, axis=0).astype('float64')
    test.loc[recorded_form(test.type_text) == UNKNOWN, 'with_form'] = test.baseline
    keys = ['season','source_row','game_id','split','made']
    saved = pd.read_csv(SAVED, usecols=keys+[MODEL])
    saved = saved[saved.split.isin(['test','playoffs'])]
    assert len(saved) == len(test)
    checked = test[keys+['scope','baseline','with_form']].merge(saved,on=keys,validate='one_to_one')
    assert len(checked) == len(saved)
    difference = float((checked.baseline - checked[MODEL]).abs().max())
    assert difference < 1e-6, difference
    checked.to_csv(OUTPUT, index=False)
    by_game = game_totals(checked,'baseline','with_form')
    result = []
    for scope, g in by_game.groupby(level='scope'):
        scores = score(g)
        scores['brier_context'] = scores.pop('brier_distance')
        scores['log_context'] = scores.pop('log_distance')
        result.append(dict(season=TEST, scope=scope, **scores))
    OUT.mkdir(exist_ok=True,parents=True)
    pd.DataFrame(result).to_csv(OUT/'context.csv',index=False)
    write_json(OUT/'context_design.json',dict(model=MODEL,depth=depth,seeds=list(SEEDS),
        selection_season=VALIDATION,training_seasons=design['train'],test_season=TEST,
        max_original_probability_difference=difference))
    print('CONTEXT_CHECK', json.dumps(result), 'reproduction tolerance:', difference, flush=True)


if __name__ == '__main__':
    compare()
