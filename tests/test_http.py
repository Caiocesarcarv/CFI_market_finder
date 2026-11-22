import pytest
import requests

from app.services import http
from app.services.http import ExternalServiceError, request_json


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        if self._body is None:
            raise ValueError("sem json")
        return self._body


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def patch_responses(monkeypatch, *responses):
    calls = iter(responses)

    def fake(*args, **kwargs):
        r = next(calls)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(http._session, "request", fake)


def test_success(monkeypatch):
    patch_responses(monkeypatch, FakeResp(200, {"ok": True}))
    assert request_json("GET", "http://x", source="T") == {"ok": True}


def test_retries_then_succeeds(monkeypatch):
    patch_responses(monkeypatch, requests.Timeout(), FakeResp(503, {}), FakeResp(200, {"ok": 1}))
    assert request_json("GET", "http://x", source="T") == {"ok": 1}


def test_connection_error_becomes_503(monkeypatch):
    patch_responses(monkeypatch, *[requests.ConnectionError()] * 3)
    with pytest.raises(ExternalServiceError) as e:
        request_json("GET", "http://x", source="T")
    assert e.value.status_code == 503 and "conexão" in e.value.message


def test_invalid_key(monkeypatch):
    patch_responses(monkeypatch, FakeResp(401, {"error": "x"}))
    with pytest.raises(ExternalServiceError) as e:
        request_json("GET", "http://x", source="T")
    assert "chave" in e.value.message


def test_rate_limit(monkeypatch):
    patch_responses(monkeypatch, *[FakeResp(429, {})] * 3)
    with pytest.raises(ExternalServiceError) as e:
        request_json("GET", "http://x", source="T")
    assert e.value.status_code == 429


def test_provider_message_on_400(monkeypatch):
    patch_responses(monkeypatch, FakeResp(400, {"error": {"message": "modelo inexistente"}}))
    with pytest.raises(ExternalServiceError) as e:
        request_json("GET", "http://x", source="T")
    assert e.value.message == "modelo inexistente"


def test_non_json(monkeypatch):
    patch_responses(monkeypatch, FakeResp(200, None))
    with pytest.raises(ExternalServiceError):
        request_json("GET", "http://x", source="T")
