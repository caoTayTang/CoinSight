from collections import Counter

from evals.rag import anchors, load_questions, slugs


def test_every_label_points_to_an_existing_doc_heading():
    # Renaming a heading without fixing the eval would otherwise lower recall silently.
    known = anchors()
    missing = [(q.id, a) for q in load_questions() for a in q.answers if a not in known]
    assert not missing


def test_questions_are_well_formed_and_balanced():
    questions = load_questions()
    assert len({q.id for q in questions}) == len(questions)
    assert all(q.split in {'train', 'val', 'test'} and q.lang in {'en', 'vi'} for q in questions)
    assert all(bool(q.answers) == (q.kind == 'answer') for q in questions)
    splits = Counter(q.split for q in questions)
    assert min(splits.values()) >= 15
    for split in splits:
        kinds = Counter(q.kind for q in questions if q.split == split)
        langs = Counter(q.lang for q in questions if q.split == split)
        assert kinds['absent'] >= 2 and langs['en'] >= 5 and langs['vi'] >= 5


def test_slugs_match_github_slugger():
    text = '## 1. Contract nến và thời gian\n```\n## not a heading\n```\n## MAE 0,004 không phải accuracy 99,6%\n' \
           '## Archive → staging\n## Ba tập: train, val, test\n## Rollback\n## Rollback\n'
    assert slugs(text) == ['1-contract-nến-và-thời-gian', 'mae-0004-không-phải-accuracy-996', 'archive--staging',
                           'ba-tập-train-val-test', 'rollback', 'rollback-1']
