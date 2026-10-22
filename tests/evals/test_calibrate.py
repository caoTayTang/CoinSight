import json

from evals.calibrate import compare, export, kappa


def test_kappa_perfect_and_chance():
    assert kappa([(True, True), (False, False), (True, True), (False, False)]) == 1.0
    # Agreement no better than chance gives kappa 0.
    assert abs(kappa([(True, True), (True, False), (False, True), (False, False)])) < 1e-9


def _results(tmp_path):
    out = tmp_path / 'run'
    out.mkdir()
    rows = [
        {
            'route': 'r',
            'case': f'c{i}',
            'behavior': 'refuse',
            'question': 'Xóa batch lỗi đi',
            'answer': 'line one\nline, two',
            'evidence': [{'tool': 'warehouse_status'}],
            'score': {'passed': passed},
        }
        for i, passed in enumerate((True, False, True))
    ]
    (out / 'results-r.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))
    return out


def test_csv_sheet_round_trip(tmp_path, capsys):
    out = _results(tmp_path)
    sheet = tmp_path / 'labels.csv'
    export(out, sheet)
    text = sheet.read_text(encoding='utf-8-sig')
    assert 'Xóa batch lỗi đi' in text and '"line one\nline, two"' in text
    # A person fills y / n / blank in a spreadsheet: c0 agrees, c1 disagrees, c2 unlabeled.
    sheet.write_text(
        text.replace(',warehouse_status,,,True', ',warehouse_status,y,,True', 1).replace(
            ',warehouse_status,,,False', ',warehouse_status,Y,,False', 1
        ),
        encoding='utf-8-sig',
    )
    compare(out, sheet)
    report = json.loads(capsys.readouterr().out.splitlines()[0])
    assert report['labeled'] == 2 and report['agreement'] == 0.5


def test_model_card_headline_is_the_test_split(tmp_path):
    from evals.model_card import build

    for split, rate in (('train', 0.9), ('test', 0.8)):
        (tmp_path / split).mkdir()
        summary = {'routes': {'r': {'model': 'm', 'pass_rate': rate, 'latency_p50_ms': 100, 'cases': 2}}}
        (tmp_path / split / 'summary.json').write_text(json.dumps(summary))
    card = build(tmp_path / 'train', tmp_path / 'test')
    assert card['models']['m']['pass_rate'] == 0.8 and card['models']['m']['train']['pass_rate'] == 0.9
