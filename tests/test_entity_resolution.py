import pytest

er = pytest.importorskip("entity_resolution", exc_type=ImportError)


def test_pair_evaluation_counts_duplicates_missed_by_blocking():
    truth = {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B"}
    records = [{"unique_id": key} for key in truth]
    candidates = [
        {"left": "a1", "right": "a2", "match_probability": 0.96},
        {"left": "a1", "right": "b1", "match_probability": 0.99},
    ]
    result = er.evaluate_pairs(records, truth, candidates, 0.95)
    assert result["all_possible_pairs"] == 10
    assert result["candidate_pairs"] == 2
    assert result["true_duplicate_pairs"] == 4
    assert result["true_positives"] == 1
    assert result["false_positives"] == 1
    assert result["false_negatives"] == 3
    assert result["precision"] == 0.5
    assert result["recall"] == result["blocking_recall"] == 0.25
    assert result["false_merge_examples"] == [("a1", "b1")]


def test_splink_scores_names_and_dob_not_shared_devices():
    training, training_truth = er.synthetic_customers("train", 120, 42)
    held_out, held_out_truth = er.synthetic_customers("test", 80, 73)
    assert set(training_truth.values()).isdisjoint(held_out_truth.values())
    assert all("training_label" not in row for row in held_out)
    model = er.train_model(training, training_truth)
    candidates = er.score_candidates(held_out, model)
    changed_devices = [
        {**row, "device_id": f"unique-device-{index}"} for index, row in enumerate(held_out)
    ]
    assert er.score_candidates(changed_devices, model) == candidates
    exact_duplicate = next(
        row for row in candidates if {row["left"], row["right"]} == {"test-001-0", "test-001-1"}
    )
    assert exact_duplicate["match_probability"] > 0.95
    evaluation = er.evaluate_pairs(held_out, held_out_truth, candidates, 0.95)
    assert evaluation["true_duplicate_pairs"] == 80
    assert evaluation["false_positives"] > 0  # Ambiguous synthetic people must remain visible.
    assert evaluation["false_negatives"] > 0
    assert evaluation["blocking_recall"] < 1
