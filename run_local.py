#!/usr/bin/env python3
"""Ejecutor local: conserva la sesión de Chromium y consulta cada dos horas."""
from __future__ import annotations

import os
import time
from datetime import datetime

from tracker import run_monitor

INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", str(2 * 60 * 60)))


def main() -> None:
    os.environ.setdefault("LOCAL_PROFILE_DIR", "aliexpress_profile")
    os.environ.setdefault("LOCAL_HEADLESS", "0")
    print(f"Monitor local iniciado. Intervalo: {INTERVAL_SECONDS // 3600} h.", flush=True)
    while True:
        print(f"\n[{datetime.now().isoformat(timespec='seconds')}] Nueva comprobación", flush=True)
        status = run_monitor()
        print(f"Comprobación terminada con código {status}. Próxima en {INTERVAL_SECONDS // 60} minutos.", flush=True)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
