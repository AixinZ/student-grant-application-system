import io
from pathlib import Path

import pytest

from grant_app.csv_scoring.errors import CsvValidationError
from grant_app.csv_scoring.parser import (
    canonical_header,
    parse_upload,
    validate_selected_headers,
)


def rows(count: int, fields: int = 2) -> str:
    return "".join(",".join(str(i) for _ in range(fields)) + "\n" for i in range(count))


def upload(tmp_path, text, *, min_rows=1, max_rows=10, max_bytes=100_000_000):
    return parse_upload(io.BytesIO(text.encode()), tmp_path, upload_id="u1",
                        max_bytes=max_bytes, min_rows=min_rows, max_rows=max_rows,
                        ttl_seconds=3_600)


def test_parse_upload_strips_bom_for_matching_but_preserves_header(tmp_path):
    parsed = parse_upload(
        io.BytesIO(("\ufeffAccount ID, Amount\n" + rows(100_000)).encode()),
        tmp_path, upload_id="u1", max_bytes=100_000_000,
        min_rows=100_000, max_rows=250_000, ttl_seconds=3_600,
    )
    assert parsed.headers[:2] == ("Account ID", " Amount")
    assert parsed.canonical_headers[:2] == ("account id", "amount")
    assert parsed.row_count == 100_000
    assert parsed.size_bytes == len(("\ufeffAccount ID, Amount\n" + rows(100_000)).encode())
    assert parsed.path.read_bytes().startswith("\ufeffAccount ID".encode())


def test_header_matching_and_selection_are_trimmed_and_casefolded(tmp_path):
    assert canonical_header("  Amount ") == "amount"
    assert validate_selected_headers(("Account ID", " Amount"), (" account id ", "AMOUNT")) == (
        "account id", "amount"
    )


@pytest.mark.parametrize("header", ["a,a", "A, a ", "SCORE", " score "])
def test_rejects_duplicate_or_reserved_headers(tmp_path, header):
    with pytest.raises(CsvValidationError):
        upload(tmp_path, header + "\n1,2\n", min_rows=1)


def test_rejects_uneven_rows_and_malformed_encoding(tmp_path):
    with pytest.raises(CsvValidationError):
        upload(tmp_path, "a,b\n1\n", min_rows=1)
    with pytest.raises(CsvValidationError):
        parse_upload(io.BytesIO(b"a,b\n\xff,2\n"), tmp_path, upload_id="u1",
                     max_bytes=1000, min_rows=1, max_rows=2, ttl_seconds=3_600)


@pytest.mark.parametrize("text", ["account;amount\nA;10\n", "account\tamount\nA\t10\n", "account|amount\nA|10\n"])
def test_rejects_non_comma_delimited_csv(tmp_path, text):
    with pytest.raises(CsvValidationError):
        upload(tmp_path, text, min_rows=1)


def test_accepts_quoted_commas_and_uses_configured_ttl(tmp_path):
    parsed = parse_upload(
        io.BytesIO(b'account,note\nA,"comma, inside"\n'),
        tmp_path,
        upload_id="u1",
        max_bytes=100_000_000,
        min_rows=1,
        max_rows=10,
        ttl_seconds=17,
        now=100.0,
    )

    assert parsed.headers == ("account", "note")
    assert parsed.expires_at == 117.0


def test_rejects_missing_header_and_invalid_row_counts(tmp_path):
    with pytest.raises(CsvValidationError):
        upload(tmp_path, "", min_rows=1)
    with pytest.raises(CsvValidationError):
        upload(tmp_path, "a\n", min_rows=1)
    with pytest.raises(CsvValidationError):
        upload(tmp_path, "a\n1\n2\n", min_rows=3, max_rows=3)
    with pytest.raises(CsvValidationError):
        upload(tmp_path, "a\n" + rows(4, 1), min_rows=1, max_rows=3)


def test_rejects_byte_limit_and_cleans_staged_files(tmp_path):
    with pytest.raises(CsvValidationError):
        upload(tmp_path, "a\n1\n", min_rows=1, max_bytes=2)
    assert list(tmp_path.iterdir()) == []


def test_selected_unknown_header_is_rejected_without_echoing_values():
    with pytest.raises(CsvValidationError) as exc:
        validate_selected_headers(("Account ID",), ("secret-cell",))
    assert "secret-cell" not in str(exc.value)
