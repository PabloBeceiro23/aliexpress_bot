#!/usr/bin/env python3
"""Prueba local del formato de carga de imagen y plantilla de WhatsApp."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker import WhatsAppNotifier


class FakeResponse:
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return {"id": "test-media-id"}


def main() -> None:
    os.environ.update(
        {
            "WA_ACCESS_TOKEN": "test-token",
            "WA_PHONE_NUMBER_ID": "123456",
            "WA_RECIPIENT": "+34600111222",
            "WA_TEMPLATE_FAILURE": "aliexpress_tracker_error",
        }
    )
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()

    with tempfile.TemporaryDirectory() as directory:
        screenshot = Path(directory) / "failure.png"
        screenshot.write_bytes(b"not-a-real-png-but-enough-for-request-test")
        with patch("tracker.requests.post", side_effect=fake_post):
            WhatsAppNotifier().send_failure(RuntimeError("fallo de prueba"), screenshot)

    assert len(calls) == 2, f"Se esperaban 2 solicitudes, se obtuvieron {len(calls)}"
    assert calls[0][0].endswith("/123456/media")
    assert calls[0][1]["data"]["messaging_product"] == "whatsapp"
    payload = calls[1][1]["json"]
    assert calls[1][0].endswith("/123456/messages")
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "aliexpress_tracker_error"
    assert payload["template"]["components"][0]["type"] == "header"
    assert payload["template"]["components"][0]["parameters"][0]["image"]["id"] == "test-media-id"
    assert len(payload["template"]["components"][1]["parameters"]) == 3
    print("[notifier-test] OK")


if __name__ == "__main__":
    main()
