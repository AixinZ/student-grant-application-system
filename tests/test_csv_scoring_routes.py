import io
import json
import time

import joblib
import pytest

from grant_app import create_app
from grant_app.csv_scoring.models import ModelSpec
from grant_app.csv_scoring.registry import ModelRegistry


class DeterministicAdapter:
    def score_rows(self, rows):
        return [0.25 for _ in rows]


class TinyIsolationForest:
    feature_names_in_ = ("account id", "amount")

    def decision_function(self, rows):
        return [0.0 for _ in rows]


def scoring_app(tmp_path, **overrides):
    registry = ModelRegistry((
        ModelSpec(
            model_id="deterministic",
            display_name="Deterministic test model",
            model_type="supervised",
            required_columns=("amount",),
            version="1",
            adapter=DeterministicAdapter(),
        ),
    ))
    config = {
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'routes.sqlite'}",
        "CSV_SCORING_TEMP_DIR": str(tmp_path / "csv-scoring"),
        "CSV_SCORING_MIN_ROWS": 2,
        "CSV_SCORING_MAX_ROWS": 10,
        "CSV_SCORING_CHUNK_SIZE": 1,
        "CSV_SCORING_MODEL_REGISTRY": registry,
    }
    config.update(overrides)
    return create_app(config)


def upload_csv(client, body=b"name,amount\nAda,10\nBob,20\n", filename="private.csv"):
    return client.post(
        "/csv-scoring/uploads",
        data={"file": (io.BytesIO(body), filename)},
        content_type="multipart/form-data",
    )


def completed_job(client, upload_id):
    response = client.post(
        "/csv-scoring/jobs",
        json={
            "upload_id": upload_id,
            "selected_fields": ["name"],
            "model_id": "deterministic",
        },
    )
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]
    for _ in range(50):
        status = client.get(f"/csv-scoring/jobs/{job_id}")
        assert status.status_code == 200
        payload = status.get_json()
        if payload["status"] in {"completed", "failed"}:
            return job_id, payload
        time.sleep(0.01)
    pytest.fail("CSV scoring job did not complete")


def test_upload_metadata_job_status_and_atomic_download_expose_only_safe_metadata(tmp_path):
    app = scoring_app(tmp_path)
    client = app.test_client()

    uploaded = upload_csv(client)

    assert uploaded.status_code == 201
    upload = uploaded.get_json()
    assert set(upload) == {"upload_id", "fields", "row_count", "size_bytes"}
    assert upload["fields"] == ["name", "amount"]
    assert upload["row_count"] == 2
    assert upload["size_bytes"] > 0
    assert "private.csv" not in uploaded.get_data(as_text=True)

    metadata = client.get(f"/csv-scoring/uploads/{upload['upload_id']}")
    assert metadata.status_code == 200
    assert metadata.get_json() == upload

    job_id, status = completed_job(client, upload["upload_id"])
    assert status == {
        "job_id": job_id,
        "status": "completed",
        "progress_rows": 2,
    }

    download = client.get(f"/csv-scoring/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.mimetype == "text/csv"
    assert download.headers["Content-Disposition"] == f'attachment; filename=scored_{job_id}.csv'
    assert download.data == b"\xef\xbb\xbfname,SCORE\r\nAda,0.250000\r\nBob,0.250000\r\n"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (b"name,amount\nAda,10\n", 400),
        (b"name,amount\n" + b"Ada,10\n" * 11, 400),
    ],
)
def test_invalid_csv_returns_a_stable_json_error_without_cell_values(tmp_path, body, status):
    client = scoring_app(tmp_path).test_client()

    response = upload_csv(client, body=body)

    assert response.status_code == status
    assert response.get_json() == {"error": "invalid_csv"}
    assert "Ada" not in response.get_data(as_text=True)


def test_job_rejects_missing_required_model_columns_and_unavailable_models(tmp_path):
    client = scoring_app(tmp_path).test_client()
    upload_id = upload_csv(client, body=b"name,other\nAda,x\nBob,y\n").get_json()["upload_id"]

    missing_columns = client.post(
        "/csv-scoring/jobs",
        json={"upload_id": upload_id, "selected_fields": ["name"], "model_id": "deterministic"},
    )
    unavailable = client.post(
        "/csv-scoring/jobs",
        json={"upload_id": upload_id, "selected_fields": ["name"], "model_id": "not-a-model"},
    )

    assert missing_columns.status_code == 400
    assert missing_columns.get_json() == {"error": "missing_model_columns"}
    assert unavailable.status_code == 400
    assert unavailable.get_json() == {"error": "model_unavailable"}


@pytest.mark.parametrize(
    "url",
    [
        "/csv-scoring/uploads/not-an-upload-id",
        "/csv-scoring/jobs/not-a-job-id",
        "/csv-scoring/jobs/not-a-job-id/download",
    ],
)
def test_unknown_scoring_ids_return_json_not_found_errors(tmp_path, url):
    response = scoring_app(tmp_path).test_client().get(url)

    assert response.status_code == 404
    assert response.get_json() == {"error": "not_found"}


def test_job_rejects_invalid_selected_fields_and_multiple_models(tmp_path):
    client = scoring_app(tmp_path).test_client()
    upload_id = upload_csv(client).get_json()["upload_id"]

    invalid_fields = client.post(
        "/csv-scoring/jobs",
        json={"upload_id": upload_id, "selected_fields": ["private cell"], "model_id": "deterministic"},
    )
    multiple_models = client.post(
        "/csv-scoring/jobs",
        json={"upload_id": upload_id, "selected_fields": ["name"], "model_id": ["deterministic"]},
    )

    assert invalid_fields.status_code == 400
    assert invalid_fields.get_json() == {"error": "invalid_job"}
    assert "private cell" not in invalid_fields.get_data(as_text=True)
    assert multiple_models.status_code == 400
    assert multiple_models.get_json() == {"error": "invalid_job"}


def test_csv_scoring_csrf_failure_is_a_json_400(tmp_path):
    app = scoring_app(tmp_path, WTF_CSRF_ENABLED=True)

    response = upload_csv(app.test_client())

    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid_request"}


def test_csv_scoring_oversized_request_uses_json_413_without_filename(tmp_path):
    client = scoring_app(tmp_path, MAX_CONTENT_LENGTH=20).test_client()

    response = upload_csv(client, filename="very-private.csv")

    assert response.status_code == 413
    assert response.get_json() == {"error": "file_too_large"}
    assert "very-private.csv" not in response.get_data(as_text=True)


def test_default_registry_registers_the_configured_experimental_iforest(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    joblib.dump(TinyIsolationForest(), model_dir / "isolation_forest_model.joblib")
    (model_dir / "iforest_manifest.json").write_text(
        json.dumps(
            {
                "model_id": "experimental-iforest",
                "version": "1",
                "required_headers": ["account id", "amount"],
                "score_direction": "lower_is_higher_risk",
                "calibration": {"low": -1.0, "high": 1.0},
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'default-registry.sqlite'}",
            "CSV_SCORING_TEMP_DIR": str(tmp_path / "csv-scoring"),
            "CSV_SCORING_MODEL_DIR": str(model_dir),
        }
    )

    assert [model.model_id for model in app.config["CSV_SCORING_MODEL_REGISTRY"].list_available()] == [
        "experimental-iforest"
    ]


def test_worker_failure_logs_only_sanitized_context_and_download_stays_unavailable(tmp_path, caplog):
    class FailingAdapter:
        def score_rows(self, _rows):
            raise RuntimeError("private-cell-value /secret/models")

    registry = ModelRegistry((
        ModelSpec(
            model_id="failing",
            display_name="Failing model",
            model_type="supervised",
            required_columns=("amount",),
            version="1",
            adapter=FailingAdapter(),
        ),
    ))
    client = scoring_app(tmp_path, CSV_SCORING_MODEL_REGISTRY=registry).test_client()
    upload_id = upload_csv(client).get_json()["upload_id"]
    created = client.post(
        "/csv-scoring/jobs",
        json={"upload_id": upload_id, "selected_fields": ["name"], "model_id": "failing"},
    )
    job_id = created.get_json()["job_id"]

    for _ in range(50):
        status = client.get(f"/csv-scoring/jobs/{job_id}")
        if status.get_json()["status"] == "failed":
            break
        time.sleep(0.01)
    else:
        pytest.fail("CSV scoring job did not fail")

    assert status.get_json() == {
        "job_id": job_id,
        "status": "failed",
        "progress_rows": 0,
        "error": "processing_failed",
    }
    download = client.get(f"/csv-scoring/jobs/{job_id}/download")
    assert download.status_code == 400
    assert download.get_json() == {"error": "result_not_ready"}
    assert "private-cell-value" not in caplog.text
    assert "/secret/models" not in caplog.text
