#!/usr/bin/env bash
set -euo pipefail

python -m compileall -q tracker.py
python tracker.py --self-test
python scripts/test_notifier.py
git diff --check
grep -Fq "cron: '17 */2 * * *'" .github/workflows/tracker.yml
grep -Fq 'actions/upload-artifact@v4' .github/workflows/tracker.yml
grep -Fq 'WA_ACCESS_TOKEN' .github/workflows/tracker.yml
grep -Fq 'CAPTCHA' README.md
test -f price_state.json
echo 'Validación estática: OK'
