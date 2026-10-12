from scripts.evaluate_videos import cases, metrics


def test_manifest_is_fixed_and_balanced():
    matrix = cases()
    assert len(matrix) == 40
    assert sum(split == 'dev' for _, _, split in matrix) == 20
    assert sum(split == 'holdout' for _, _, split in matrix) == 10
    assert len({c.key for c, _, _ in matrix}) == 5
    assert len({(c.key, item.key) for c, item, _ in matrix}) == len(matrix)


def row(videos, known=True):
    return {'known_available': known, 'availability_notes': 'Independent manual search.',
            'proposed': {'complete': True, 'videos': videos}}


def reviewed(label='relevant', contradiction=False):
    return {'review': label, 'contradiction': contradiction, 'review_notes': 'Content reviewed.'}


def test_no_results_cannot_pass_gate():
    assert not metrics([row([])], 'proposed')['release_gate']


def test_unreviewed_cannot_pass_gate():
    assert not metrics([row([{'review': 'unreviewed'}])], 'proposed')['release_gate']


def test_uncertain_counts_as_unsuitable():
    result = metrics([row([reviewed('uncertain')])], 'proposed')
    assert result['precision'] == 0 and result['coverage'] == 0
    assert not result['release_gate']


def test_incomplete_benchmark_cannot_pass():
    rows = [row([reviewed()]), {'known_available': True}]
    assert not metrics(rows, 'proposed')['release_gate']


def test_contradiction_cannot_pass():
    assert not metrics([row([reviewed(contradiction=True)])], 'proposed')['release_gate']


def test_reviewed_coverage_and_precision_gate():
    good = row([reviewed()])
    assert metrics([good], 'proposed')['release_gate']
    assert not metrics([good, row([])], 'proposed')['release_gate']
