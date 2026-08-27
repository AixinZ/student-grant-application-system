import json

import joblib
import pytest

from grant_app.csv_scoring.adapters.isolation_forest import IsolationForestAdapter
from grant_app.csv_scoring.calibration import format_score, normalize_score
from grant_app.csv_scoring.errors import ModelUnavailableError
from grant_app.csv_scoring.models import ModelSpec
from grant_app.csv_scoring.registry import ModelRegistry


class TinyIsolationForest:
    """Pickleable stand-in for the pre-trained pipeline boundary."""

    feature_names_in_ = ("account id", "amount")

    def decision_function(self, values):
        return [-0.5 if row[1] == 10 else 0.5 for row in values]


class StaticAdapter:
    def score_rows(self, rows):
        return [0.25 for _ in rows]


def model_spec(adapter=None):
    return ModelSpec(
        model_id="manual-review",
        display_name="Manual review model",
        model_type="supervised",
        required_columns=("Account ID", " Amount "),
        version="1",
        adapter=adapter or StaticAdapter(),
    )


def test_registry_gets_registered_model_and_canonicalizes_required_headers():
    registry = ModelRegistry()
    spec = model_spec()
    registry.register(spec)

    loaded = registry.get("manual-review")

    assert loaded is spec
    assert loaded.required_columns == ("account id", "amount")
    assert loaded.matches_headers((" ACCOUNT ID ", "AMOUNT", "notes"))


def test_registry_rejects_unknown_model_with_a_safe_error():
    with pytest.raises(ModelUnavailableError) as error:
        ModelRegistry().get("not-configured")

    assert "not-configured" not in str(error.value)


def test_registry_omits_an_adapter_that_is_not_available():
    class UnavailableAdapter(StaticAdapter):
        availability_reason = "Model is temporarily unavailable"

    registry = ModelRegistry()
    registry.register(model_spec(UnavailableAdapter()))

    assert registry.list_available() == ()
    assert registry.availability_reason("manual-review") == "Model is temporarily unavailable"


def test_normalize_score_preserves_supervised_probability_direction():
    assert normalize_score(0.125, low=0.0, high=1.0) == 0.125


def test_normalize_score_reverses_unsupervised_anomaly_direction():
    assert normalize_score(-0.5, low=-1.0, high=1.0, reverse=True) == 0.75


def test_normalize_score_clips_to_fixed_training_bounds():
    assert normalize_score(-2.0, low=-1.0, high=1.0) == 0.0
    assert normalize_score(0.0, low=-1.0, high=1.0) == 0.5
    assert normalize_score(2.0, low=-1.0, high=1.0) == 1.0


def test_normalize_score_rejects_equal_bounds():
    with pytest.raises(ValueError):
        normalize_score(0.5, low=1.0, high=1.0)


def test_format_score_uses_six_decimal_places():
    assert format_score(0.125) == "0.125000"


def test_isolation_forest_adapter_loads_manifest_orders_columns_and_calibrates(tmp_path):
    artifact_path = tmp_path / "model.joblib"
    manifest_path = tmp_path / "manifest.json"
    joblib.dump(TinyIsolationForest(), artifact_path)
    manifest_path.write_text(
        json.dumps(
            {
                "model_id": "experimental-iforest",
                "version": "1",
                "required_headers": ["account id", "amount"],
                "score_direction": "lower_is_higher_risk",
                "calibration": {"low": -1.0, "high": 1.0},
            }
        )
    )

    adapter = IsolationForestAdapter.from_artifact(artifact_path, manifest_path)

    assert adapter.score_rows(({"amount": 10, "account id": "A"},)) == [0.75]


def test_isolation_forest_adapter_hides_artifact_load_details(tmp_path):
    with pytest.raises(ModelUnavailableError) as error:
        IsolationForestAdapter.from_artifact(tmp_path / "secret.joblib", tmp_path / "manifest.json")

    assert "secret.joblib" not in str(error.value)
