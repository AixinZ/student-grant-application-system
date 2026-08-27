"""Browser-page contract tests for the CSV scoring workflow."""

from grant_app.csv_scoring.models import ModelSpec
from grant_app.csv_scoring.registry import ModelRegistry


def test_csv_scoring_page_exposes_an_accessible_safe_workflow(client):
    """Catch a missing page or controls that prevent an operator from scoring."""
    response = client.get("/csv-scoring")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'href="/csv-scoring"' in page
    assert 'id="csv-scoring-file"' in page
    assert 'id="csv-scoring-drop-zone"' in page
    assert 'aria-describedby="csv-scoring-file-help"' in page
    assert 'id="csv-scoring-fields"' in page
    assert 'aria-live="polite"' in page
    assert 'id="csv-scoring-model"' in page
    assert 'id="csv-scoring-submit"' in page
    assert 'id="csv-scoring-status"' in page
    assert 'id="csv-scoring-download"' in page
    assert 'name="csrf_token"' in page
    assert "0..1" in page
    assert "risk evidence" in page


def test_csv_scoring_page_lists_available_registered_models(app):
    """Catch a page that omits a model that the scoring API can accept."""
    class AvailableAdapter:
        def score_rows(self, rows):
            return [0.0 for _ in rows]

    app.config["CSV_SCORING_MODEL_REGISTRY"] = ModelRegistry((
        ModelSpec(
            model_id="test-model",
            display_name="Test model",
            model_type="supervised",
            required_columns=("amount",),
            version="2026.08",
            adapter=AvailableAdapter(),
        ),
    ))

    page = app.test_client().get("/csv-scoring").get_data(as_text=True)

    assert '<option value="test-model">Test model (2026.08)</option>' in page
