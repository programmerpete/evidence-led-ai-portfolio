"""Reproducible synthetic rules-vs-ML experiment; no bank data or customer actions."""

import json

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, precision_score, recall_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def synthetic_period(rng, count, shifted=False):
    # Abstract standardised features, not a validated fraud typology.
    # Labels are sampled probabilistically, not copied from the baseline rule.
    features = rng.normal(size=(count, 3))
    if shifted:
        features[:, 0] += 0.8
    coefficients = np.array([1.4, 1.0, -0.7] if not shifted else [0.3, 1.0, -0.7])
    probability = 1 / (1 + np.exp(-(-5.0 + features @ coefficients)))
    labels = rng.binomial(1, probability)
    return features, labels


def evaluate(labels, scores, threshold):
    alerts = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(labels, alerts, labels=[0, 1]).ravel()
    return {
        "rows": len(labels),
        "positive_rate": float(np.mean(labels)),
        "average_precision": float(average_precision_score(labels, scores)),
        "precision": float(precision_score(labels, alerts, zero_division=0)),
        "recall": float(recall_score(labels, alerts, zero_division=0)),
        "alert_rate": float(np.mean(alerts)),
        "threshold": float(threshold),
        "counts": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def run_experiment():
    rng = np.random.default_rng(42)
    train_x, train_y = synthetic_period(rng, 12000)
    validation_x, _ = synthetic_period(rng, 4000)
    test_x, test_y = synthetic_period(rng, 6000)
    shifted_x, shifted_y = synthetic_period(rng, 6000, shifted=True)
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=42))
    model.fit(train_x, train_y)

    # Freeze both thresholds on validation, never tune on test or shifted labels.
    # A 5% validation alert budget is a teaching assumption, not a production SLA.
    model_threshold = np.quantile(model.predict_proba(validation_x)[:, 1], 0.95)
    rule_threshold = np.quantile(validation_x[:, 0] + validation_x[:, 1], 0.95)
    report = {
        "seed": 42,
        "data": "synthetic-only; independent simulated periods, not real chronological data",
        "metric_note": "Average precision is used, not trapezoidal PR-AUC or accuracy.",
        "limitations": [
            "Synthetic performance is not evidence of real-world fraud detection ability.",
            "Shifted period deliberately changes feature distribution AND label relationship.",
            "Scores are not calibrated for real customers; no automatic deployment or decision.",
        ],
        "periods": {},
    }
    for name, features, labels in [
        ("held_out", test_x, test_y),
        ("shifted", shifted_x, shifted_y),
    ]:
        report["periods"][name] = {
            "rule_baseline": evaluate(labels, features[:, 0] + features[:, 1], rule_threshold),
            "logistic_challenger": evaluate(
                labels, model.predict_proba(features)[:, 1], model_threshold
            ),
            "feature_mean_shift_from_training": (
                features.mean(axis=0) - train_x.mean(axis=0)
            ).tolist(),
        }
    return report


if __name__ == "__main__":
    print(json.dumps(run_experiment(), indent=2))
