#!/usr/bin/env python3
"""Prueba local de las peticiones de Telegram."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracker import TelegramNotifier

class FakeResponse:
    ok = True
    status_code = 200
    text = ""
    def json(self):
        return {"ok": True, "result": {}}

def main() -> None:
    os.environ.update({"TELEGRAM_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "123456"})
    calls = []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse()
    with tempfile.TemporaryDirectory() as directory:
        screenshot = Path(directory) / "failure.png"
        screenshot.write_bytes(b"test-image")
        with patch("tracker.requests.post", side_effect=fake_post):
            notifier = TelegramNotifier()
            notifier.send_failure(RuntimeError("fallo de prueba"), screenshot)
            notifier.send_price_drop("Reloj", 300.0, 250.0)
    assert len(calls) == 2
    assert calls[0][0].endswith("/sendPhoto")
    assert calls[0][1]["data"]["chat_id"] == "123456"
    assert calls[1][0].endswith("/sendMessage")
    assert "Bajada de precio" in calls[1][1]["data"]["text"]
    print("[notifier-test] OK")

if __name__ == "__main__":
    main()
