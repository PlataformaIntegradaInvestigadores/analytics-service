import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.cli import main
from app.core.config import Settings
from app.core.json_io import decode_json, read_json_file
from app.core.request_limits import RequestBodyLimitMiddleware
from app.domain.common import AnalyticsError
from app.domain.corpus import curate
from app.domain.forecasting import backtest, error_metrics, reference_forecast
from app.main import create_app


@pytest.mark.parametrize(
    "body",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e999}',
        b"\xff",
        b"{",
        b"[" * 1500 + b"0" + b"]" * 1500,
        b"1" * 5000,
    ],
)
def test_json_decoder_rejects_ambiguous_invalid_and_nonfinite_inputs(body):
    with pytest.raises(AnalyticsError) as error:
        decode_json(body)
    assert error.value.code == "invalid_json"


def test_bounded_json_file_and_utf8_bom(tmp_path):
    path = tmp_path / "request.json"
    path.write_bytes(b'\xef\xbb\xbf{"value":1.25}')
    assert read_json_file(path, max_bytes=100) == {"value": 1.25}
    with pytest.raises(AnalyticsError) as error:
        read_json_file(path, max_bytes=2)
    assert error.value.code == "input_too_large"


def test_http_limits_are_documented_and_include_trace_id():
    client = TestClient(create_app(Settings(_env_file=None, max_request_bytes=1024)))
    response = client.post("/api/v1/datasets/curate", content=b"x" * 1025)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "payload_too_large"
    assert response.headers["X-Trace-ID"]
    schema = client.get("/openapi.json").json()
    assert "413" in schema["paths"]["/datasets/curate"]["post"]["responses"]
    response = client.post(
        "/api/v1/datasets/curate",
        content=b'{"data_kind":"synthetic","data_kind":"empirical","records":[]}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_json"
    assert client.get("/health").status_code == 200


def test_cli_rejects_duplicate_keys_without_creating_database(tmp_path, capsys):
    request = tmp_path / "request.json"
    database = tmp_path / "data.sqlite"
    request.write_text(
        '{"data_kind":"synthetic","data_kind":"empirical","records":[]}',
        encoding="utf-8",
    )
    assert main(["curate", "--input", str(request), "--database", str(database)]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_json"
    assert not database.exists()


def exercise_asgi(messages, headers=(), limit=8, scope_type="http"):
    received, sent = [], []
    events = iter(messages)

    async def receive():
        return next(events)

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        received.append(scope["type"])
        if scope["type"] == "http":
            received.append(await receive())
            received.append(await receive())

    middleware = RequestBodyLimitMiddleware(downstream, limit)
    asyncio.run(middleware({"type": scope_type, "headers": headers}, receive, send))
    return received, sent


def test_streamed_and_misdeclared_body_sizes_cannot_bypass_limit():
    received, sent = exercise_asgi(
        [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"6789", "more_body": False},
        ],
        [(b"content-length", b"1")],
    )
    assert received == [] and sent[0]["status"] == 413
    _, sent = exercise_asgi(
        [{"type": "http.request", "body": b"123", "more_body": False}],
        [(b"content-length", b"2")],
    )
    assert sent[0]["status"] == 400


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"-1")],
        [(b"content-length", b"x")],
        [(b"content-length", b"1"), (b"content-length", b"1")],
        [(b"content-length", b"9" * 5000)],
    ],
)
def test_invalid_content_length_is_rejected_before_reading_body(headers):
    received, sent = exercise_asgi([], headers)
    assert received == [] and sent[0]["status"] == 400


def test_stream_replay_disconnect_websocket_and_json_error():
    received, sent = exercise_asgi(
        [
            {"type": "http.request", "body": b"12", "more_body": True},
            {"type": "http.request", "body": b"34", "more_body": False},
            {"type": "http.disconnect"},
        ]
    )
    assert sent == [] and received[1]["body"] == b"1234"
    assert received[2]["type"] == "http.disconnect"
    assert exercise_asgi([{"type": "http.disconnect"}]) == ([], [])
    assert exercise_asgi([], scope_type="websocket")[0] == ["websocket"]
    _, sent = exercise_asgi(
        [{"type": "http.request", "body": b"{", "more_body": False}],
        [(b"content-type", b"application/problem+json")],
    )
    assert sent[0]["status"] == 400


@pytest.mark.parametrize(
    "instant", ["0001-01-01T00:00:00+01:00", "9999-12-31T23:30:00-02:00"]
)
def test_extreme_timezone_dates_are_reported_not_internal_errors(record, instant):
    result = curate([record(retrieved_at=instant)], "synthetic")
    assert result["rejections"][0]["code"] == "invalid_retrieval_time"


@pytest.mark.parametrize("value", [True, 1.5, "2", None])
def test_domain_forecast_sizes_are_strict_integers(value):
    points = [{"period": "2020-01", "value": 1}]
    with pytest.raises(AnalyticsError):
        reference_forecast(points, "2020-01", value)
    with pytest.raises(AnalyticsError):
        backtest(points, "2020-01", "2020-02", "2020-03", min_train=value)


@pytest.mark.parametrize("value", [True, "1", None])
def test_metrics_refuse_non_numeric_and_boolean_counts(value):
    with pytest.raises(AnalyticsError):
        error_metrics([value], [1], [1, 2])
