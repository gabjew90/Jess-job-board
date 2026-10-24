"""Model-free tests for reading result arrays out of model replies.

Run: python -m pytest -q tests
"""
import pytest

from src import triage


def test_trailing_note_with_brackets_is_ignored():
    raw = '[{"job_id": "a", "band": "top"}]\n\nNote: scored [a] using the profile.'
    assert triage._parse_json(raw) == [{"job_id": "a", "band": "top"}]


def test_code_fence_and_preface():
    assert triage._parse_json('Here:\n```json\n[{"job_id": "b"}]\n```') == [{"job_id": "b"}]


def test_empty_or_foreign_arrays_do_not_win():
    raw = 'Omitted: [] and ids [1, 2]\n[{"job_id": "c", "band": "weak"}]'
    assert triage._parse_json(raw) == [{"job_id": "c", "band": "weak"}]


def test_split_answer_is_joined_in_order():
    raw = 'Part 1: [{"job_id": "a"}] Part 2: [{"job_id": "b"}]'
    assert [x["job_id"] for x in triage._parse_json(raw)] == ["a", "b"]


def test_nested_arrays_are_not_results():
    raw = '[{"job_id": "a", "tags": [{"job_id": "x"}]}]'
    assert triage._parse_json(raw) == [{"job_id": "a", "tags": [{"job_id": "x"}]}]


def test_cut_off_reply_raises_with_the_decode_error():
    with pytest.raises(ValueError, match="char"):
        triage._parse_json('[{"job_id": "a"}, {"job_id": "b", "r": [{"k": 1}]')
