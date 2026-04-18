import base64

import pytest

from project_mimic.vision.triton_client import (
    TritonConfig,
    TritonInferenceError,
    TritonVisionClient,
    _build_payload,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("invalid json")
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.last_url = ""
        self.last_json = {}

    def post(self, url: str, json: dict) -> _FakeResponse:
        self.last_url = url
        self.last_json = json
        return self.response


def test_build_payload_encodes_bytes_as_base64() -> None:
    payload = _build_payload(b"abc", "find button")
    encoded = payload["inputs"][0]["data"][0]
    assert encoded == base64.b64encode(b"abc").decode("ascii")


def test_infer_entities_parses_typed_entities() -> None:
    fake = _FakeClient(
        _FakeResponse(
            200,
            {
                "entities": [
                    {
                        "entity_id": "e1",
                        "label": "Search",
                        "role": "button",
                        "text": "Search Flights",
                        "x": 10,
                        "y": 20,
                        "width": 100,
                        "height": 30,
                        "confidence": 0.91,
                    }
                ]
            },
        )
    )

    client = TritonVisionClient(TritonConfig(endpoint="http://triton", model_name="ui-detector"), client=fake)
    entities = client.infer_entities(b"image-bytes", task_hint="click search")

    assert len(entities) == 1
    assert entities[0].entity_id == "e1"
    assert entities[0].confidence == 0.91
    assert fake.last_url.endswith("/v2/models/ui-detector/infer")


def test_infer_raises_on_http_error() -> None:
    fake = _FakeClient(_FakeResponse(503, {"error": "unavailable"}))
    client = TritonVisionClient(TritonConfig(endpoint="http://triton", model_name="ui-detector"), client=fake)

    with pytest.raises(TritonInferenceError):
        client.infer(b"image", task_hint="anything")
