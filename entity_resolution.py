"""Synthetic, entity-disjoint Splink experiment. Candidate links are not fraud findings."""

import json
from collections import Counter
from itertools import combinations
from random import Random

import duckdb
import pandas as pd
from splink import DuckDBAPI, Linker, SettingsCreator, block_on
from splink import comparison_library as cl


def synthetic_customers(prefix: str, entities: int, seed: int):
    rng = Random(seed)
    records, truth = [], {}
    addresses = {}
    first_names = ["amelia", "oliver", "isla", "noah", "mia", "leo", "ava", "lucas"]
    surnames = ["smith", "nguyen", "patel", "jones", "wilson", "brown", "lee", "taylor"]
    for index in range(entities):
        household = index // 2
        surname = surnames[household % len(surnames)]
        first = first_names[index % len(first_names)]
        # Deliberately ambiguous twins: distinct people, same address/DOB and similar names.
        twin = household % 10 == 0
        if twin:
            first = "alexander" if index % 2 == 0 else "alexandre"
        birthday = f"{1970 + household % 30:04d}-{1 + household % 12:02d}-{1 + household % 27:02d}"
        if not twin:
            birthday = f"{1970 + index % 40:04d}-{1 + index % 12:02d}-{1 + index % 27:02d}"
        address = addresses.setdefault(
            household, f"{household + 1} synthetic {rng.choice(['oak', 'elm', 'pine'])} street"
        )
        postcode = str(2000 + household % 30)
        for copy in range(2):
            unique_id = f"{prefix}-{index:03d}-{copy}"
            record = {
                "unique_id": unique_id,
                "name": f"{first} {surname}",
                "surname": surname,
                "dob": birthday,
                "address": address,
                "postcode": postcode,
                # Retained in source data but deliberately NOT a model comparison.
                "device_id": f"{prefix}-household-device-{household}",
            }
            if copy:
                if index % 4 == 0:
                    record["name"] = record["name"][:-1]
                    record["surname"] = surname[:-1]
                if index % 17 == 0:
                    record["name"] = f"{first[0]} {surname}"
                if index % 3 == 0:
                    record["address"] = address[:-1]
                if index % 19 == 0:
                    record["address"] = "999 synthetic relocated street"
                if index % 11 == 0:
                    record["dob"] = f"{int(birthday[:4]) + 1}{birthday[4:]}"
                if index % 13 == 0:
                    record["postcode"] = str(int(postcode) + 1)
            records.append(record)
            truth[unique_id] = f"{prefix}-person-{index}"
    return records, truth


def train_model(records, truth):
    counts = Counter(truth.values())
    true_pairs = sum(count * (count - 1) // 2 for count in counts.values())
    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=[
            cl.LevenshteinAtThresholds("name", 1),
            cl.ExactMatch("dob"),
            cl.LevenshteinAtThresholds("address", 1),
            cl.ExactMatch("postcode"),
        ],
        blocking_rules_to_generate_predictions=[block_on("dob"), block_on("surname", "postcode")],
        probability_two_random_records_match=true_pairs / (len(records) * (len(records) - 1) / 2),
    )
    training = [{**row, "training_label": truth[row["unique_id"]]} for row in records]
    with duckdb.connect(config={"threads": 1}) as connection:
        linker = Linker(
            pd.DataFrame(training), settings, DuckDBAPI(connection), set_up_basic_logging=False
        )
        linker.training.estimate_u_using_random_sampling(
            max_pairs=len(records) * (len(records) - 1) // 2, seed=42
        )
        linker.training.estimate_m_from_label_column("training_label")
        return linker.misc.save_model_to_json()


def score_candidates(records, model):
    # Evaluation labels never enter Splink inference.
    with duckdb.connect(config={"threads": 1}) as connection:
        linker = Linker(
            pd.DataFrame(records), model, DuckDBAPI(connection), set_up_basic_logging=False
        )
        predictions = linker.inference.predict(threshold_match_probability=0).as_record_dict()
    return [
        {
            "left": row["unique_id_l"],
            "right": row["unique_id_r"],
            "match_probability": float(row["match_probability"]),
        }
        for row in sorted(predictions, key=lambda row: (row["unique_id_l"], row["unique_id_r"]))
    ]


def evaluate_pairs(records, truth, candidates, threshold):
    # Recall's denominator includes true duplicates missed by blocking, not just scored pairs.
    true_pairs = {
        tuple(sorted((left, right)))
        for left, right in combinations(truth, 2)
        if truth[left] == truth[right]
    }
    candidate_pairs = {tuple(sorted((row["left"], row["right"]))) for row in candidates}
    accepted = {
        tuple(sorted((row["left"], row["right"])))
        for row in candidates
        if row["match_probability"] >= threshold
    }
    tp = len(accepted & true_pairs)
    false_merges = sorted(accepted - true_pairs)
    missed_matches = sorted(true_pairs - accepted)
    return {
        "threshold": threshold,
        "all_possible_pairs": len(records) * (len(records) - 1) // 2,
        "candidate_pairs": len(candidate_pairs),
        "true_duplicate_pairs": len(true_pairs),
        "blocking_recall": len(candidate_pairs & true_pairs) / len(true_pairs),
        "precision": tp / len(accepted) if accepted else 0.0,
        "recall": tp / len(true_pairs),
        "true_positives": tp,
        "false_positives": len(false_merges),
        "false_negatives": len(missed_matches),
        "false_merge_examples": false_merges[:3],
        "missed_match_examples": missed_matches[:3],
    }


def run_experiment():
    training, training_truth = synthetic_customers("train", 120, 42)
    held_out, held_out_truth = synthetic_customers("test", 80, 73)
    model = train_model(training, training_truth)
    candidates = score_candidates(held_out, model)
    return {
        "data": "synthetic-only; training and held-out person IDs are disjoint",
        "training_records": len(training),
        "held_out_records": len(held_out),
        "method": "Splink m from training labels; u from seeded random training pairs",
        "limitations": [
            "Thresholds 0.8/0.95/0.99 are illustrative and fixed before held-out scoring.",
            "Tiny synthetic data and correlated name/address attributes limit calibration.",
            "Shared household/device is not identity proof. Device ID is not a comparison.",
            "Scores are candidate identity matches, not fraud probabilities or confirmed identities.",
            "No graph merges, customer actions or automatic model promotion occur.",
        ],
        "evaluations": [
            evaluate_pairs(held_out, held_out_truth, candidates, threshold)
            for threshold in (0.8, 0.95, 0.99)
        ],
    }


if __name__ == "__main__":
    print(json.dumps(run_experiment(), indent=2))
