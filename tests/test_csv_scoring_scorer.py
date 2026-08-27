import csv
import tracemalloc

import pytest

from grant_app.csv_scoring.errors import ScoringError
from grant_app.csv_scoring.models import ModelSpec
from grant_app.csv_scoring.scorer import score_job


class DeterministicAdapter:
    def __init__(self):
        self.batch_sizes = []

    def score_rows(self, rows):
        self.batch_sizes.append(len(rows))
        return [float(row["amount"]) / 100 for row in rows]


def model(adapter):
    return ModelSpec(
        model_id="test-model",
        display_name="Test model",
        model_type="supervised",
        required_columns=("amount",),
        version="1",
        adapter=adapter,
    )


def write_source(path, row_count, column_count=3):
    headers = ["Account ID", " Amount "] + [f"field_{index}" for index in range(column_count - 2)]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for index in range(row_count):
            writer.writerow([f"row-{index}", index % 100, *(["x"] * (column_count - 2))])


def read_output(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def test_score_job_preserves_source_order_uses_original_selected_headers_and_reports_chunks(tmp_path):
    source = tmp_path / "source.csv"
    output = tmp_path / "result.csv"
    write_source(source, 10)
    adapter = DeterministicAdapter()
    progress = []

    count = score_job(
        source,
        output,
        selected_headers=(" account id ", "AMOUNT"),
        model=model(adapter),
        chunk_size=3,
        progress=progress.append,
    )

    assert count == 10
    assert adapter.batch_sizes == [3, 3, 3, 1]
    assert progress == [3, 6, 9, 10]
    assert read_output(output) == [
        ["Account ID", " Amount ", "SCORE"],
        *[[f"row-{index}", str(index), f"{index / 100:.6f}"] for index in range(10)],
    ]


def test_score_job_passes_only_required_model_columns_to_adapter(tmp_path):
    class SpyAdapter:
        def __init__(self):
            self.rows = []

        def score_rows(self, rows):
            self.rows.extend(dict(row) for row in rows)
            return [0.5] * len(rows)

    source = tmp_path / "source.csv"
    output = tmp_path / "result.csv"
    write_source(source, 2, column_count=4)
    adapter = SpyAdapter()

    score_job(
        source,
        output,
        selected_headers=("Account ID",),
        model=model(adapter),
        chunk_size=2,
        progress=lambda _: None,
    )

    assert adapter.rows == [{"amount": "0"}, {"amount": "1"}]


@pytest.mark.parametrize("scores", [([],), ([float("inf")],), ([1.1],)])
def test_score_job_rejects_invalid_adapter_output_without_leaking_values_or_partial_result(tmp_path, scores):
    class InvalidAdapter:
        def score_rows(self, rows):
            return scores[0]

    source = tmp_path / "source.csv"
    output = tmp_path / "result.csv"
    write_source(source, 1)

    with pytest.raises(ScoringError) as error:
        score_job(
            source, output, selected_headers=("Account ID",), model=model(InvalidAdapter()),
            chunk_size=1, progress=lambda _: None,
        )

    assert str(error.value) == "CSV scoring failed"
    assert "row-0" not in str(error.value)
    assert not output.exists()


def test_score_job_streams_a_250000_row_twenty_column_source_in_bounded_batches(tmp_path):
    class CountingAdapter:
        def __init__(self):
            self.largest_batch = 0

        def score_rows(self, rows):
            self.largest_batch = max(self.largest_batch, len(rows))
            return [0.5] * len(rows)

    source = tmp_path / "large.csv"
    output = tmp_path / "result.csv"
    write_source(source, 250_000, column_count=20)
    adapter = CountingAdapter()

    tracemalloc.start()
    try:
        count = score_job(
            source, output, selected_headers=("Account ID",), model=model(adapter),
            chunk_size=500, progress=lambda _: None,
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert count == 250_000
    assert adapter.largest_batch == 500
    assert peak < 20 * 1024 * 1024
