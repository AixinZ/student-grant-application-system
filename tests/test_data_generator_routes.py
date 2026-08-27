import io
import logging
import zipfile


class TrackingBuffer(io.BytesIO):
    def __init__(self):
        super().__init__()
        self.was_closed = False

    def close(self):
        self.was_closed = True
        super().close()


def test_get_data_generator_page(client):
    response = client.get("/data-generator")

    assert response.status_code == 200
    assert b"Data Generator" in response.data
    assert b'name="row_count"' in response.data


def test_invalid_count_returns_422_without_download(client):
    response = client.post("/data-generator", data={"row_count": "9999"})

    assert response.status_code == 422
    assert b"between 10,000 and 250,000" in response.data
    assert "attachment" not in response.headers.get("Content-Disposition", "")


def test_minimum_count_downloads_valid_xlsx(client):
    response = client.post("/data-generator", data={"row_count": "10000"})

    assert response.status_code == 200
    assert (
        response.mimetype
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "synthetic_fraud_data_10000_" in response.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.testzip() is None
    response.close()


def test_maximum_count_is_passed_to_lazy_generator(client, monkeypatch):
    from grant_app import routes

    captured = {}

    def capture_count(count):
        captured["count"] = count
        return iter(())

    monkeypatch.setattr(routes, "generate_rows", capture_count)
    monkeypatch.setattr(
        routes,
        "write_xlsx",
        lambda output, rows, expected_rows: output.write(b"test-xlsx"),
    )

    response = client.post("/data-generator", data={"row_count": "250000"})

    assert response.status_code == 200
    assert captured["count"] == 250000
    response.close()


def test_response_close_releases_temporary_file(client, monkeypatch):
    from grant_app import routes

    output = TrackingBuffer()
    monkeypatch.setattr(routes.tempfile, "TemporaryFile", lambda **_kwargs: output)
    monkeypatch.setattr(
        routes,
        "write_xlsx",
        lambda target, rows, expected_rows: target.write(b"xlsx"),
    )

    response = client.post("/data-generator", data={"row_count": "10000"})
    response.close()

    assert output.was_closed


def test_generation_failure_is_sanitized(client, monkeypatch, caplog):
    from grant_app import routes

    output = TrackingBuffer()

    def fail_export(output, rows, expected_rows):
        raise RuntimeError("private temp path /secret/output.xlsx") from OSError(
            "disk details"
        )

    monkeypatch.setattr(routes.tempfile, "TemporaryFile", lambda **_kwargs: output)
    monkeypatch.setattr(routes, "write_xlsx", fail_export)

    with caplog.at_level(logging.ERROR):
        response = client.post("/data-generator", data={"row_count": "10000"})

    assert response.status_code == 503
    assert b"could not generate" in response.data.lower()
    assert b"/secret/output.xlsx" not in response.data
    assert "data_generation_failed" in caplog.text
    assert "/secret/output.xlsx" not in caplog.text
    assert output.was_closed
