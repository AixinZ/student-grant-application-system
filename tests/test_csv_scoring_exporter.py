import csv

import pytest

from grant_app.csv_scoring.exporter import write_scored_csv
from grant_app.csv_scoring.errors import ScoringError


def read_output(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle))


def test_exporter_writes_selected_fields_then_six_decimal_scores_with_bom_and_quoting(tmp_path):
    output = tmp_path / "result.csv"

    write_scored_csv(
        (
            {"Account ID": "A,1", "Amount": "10", "Notes": "first"},
            {"Account ID": "B", "Amount": "20", "Notes": "second"},
        ),
        output,
        selected_headers=("Notes", "Account ID"),
        scores=(0.125, 1),
    )

    assert output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert read_output(output) == [
        ["Notes", "Account ID", "SCORE"],
        ["first", "A,1", "0.125000"],
        ["second", "B", "1.000000"],
    ]


def test_exporter_removes_partial_file_and_leaves_no_result_when_scores_fail(tmp_path):
    output = tmp_path / "result.csv"

    with pytest.raises(ScoringError) as error:
        write_scored_csv(
            ({"id": "first"}, {"id": "second"}),
            output,
            selected_headers=("id",),
            scores=(0.5, float("nan")),
        )

    assert str(error.value) == "CSV scoring failed"
    assert not output.exists()
    assert not list(tmp_path.glob(".result-*.csv"))


def test_exporter_rejects_mismatched_row_and_score_counts_without_creating_result(tmp_path):
    output = tmp_path / "result.csv"

    with pytest.raises(ScoringError):
        write_scored_csv(
            ({"id": "first"}, {"id": "second"}),
            output,
            selected_headers=("id",),
            scores=(0.5,),
        )

    assert not output.exists()


def test_exporter_hides_unexpected_stream_errors_and_cleans_up(tmp_path):
    output = tmp_path / "result.csv"

    def rows():
        yield {"id": "first"}
        raise RuntimeError("private-cell-value")

    with pytest.raises(ScoringError) as error:
        write_scored_csv(rows(), output, selected_headers=("id",), scores=(0.5, 0.6))

    assert str(error.value) == "CSV scoring failed"
    assert not output.exists()
