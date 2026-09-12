#!/usr/bin/env python3
"""Monitor de precio de AliExpress con alertas por WhatsApp Cloud API.

No intenta resolver ni eludir CAPTCHAs. Si la página presenta una verificación,
el proceso conserva una captura, intenta notificarla por WhatsApp y termina con
error para que GitHub Actions archive el diagnóstico.
"""
from __future__ import annotations

import json
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import requests
from playwright.sync_api import Browser, Page, sync_playwright

PRODUCT_URL = os.getenv(
    "PRODUCT_URL", "https://es.aliexpress.com/item/1005007999908066.html"
)
STATE_FILE = Path(os.getenv("STATE_FILE", "price_state.json"))
ARTIFACTS_DIR = Path(os.getenv("ARTIFACTS_DIR", "artifacts"))
REQUEST_TIMEOUT = 30


class TrackerError(RuntimeError):
    """Base class for expected monitor failures."""


class CaptchaDetectedError(TrackerError):
    """Raised when the site asks for a human verification."""


class PriceNotFoundError(TrackerError):
    """Raised when a product page is reachable but has no reliable price."""


class WhatsAppError(TrackerError):
    """Raised when the WhatsApp Cloud API declines a notification."""


@dataclass(frozen=True)
class PriceResult:
    price: float
    source: str
    title: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_message(value: str, limit: int = 700) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def parse_price(value: Any) -> Optional[float]:
    """Convert common ES/EUR price text to a positive decimal amount."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None

    text = str(value).replace("\xa0", " ")
    match = re.search(
        r"(?<![\d-])(\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?!\d)",
        text,
    )
    if not match:
        return None

    number_text = match.group(1).replace(" ", "")
    if "," in number_text:
        number_text = number_text.replace(".", "").replace(",", ".")
    elif number_text.count(".") > 1:
        number_text = number_text.replace(".", "")
    try:
        number = float(number_text)
        return number if number > 0 else None
    except ValueError:
        return None


def price_from_texts(texts: Iterable[str]) -> Optional[float]:
    for text in texts:
        price = parse_price(text)
        if price is not None:
            return price
    return None


def visible_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5_000)
    except Exception:
        return ""


def ensure_not_captcha(page: Page) -> None:
    """Stop safely on a challenge instead of interacting with it."""
    text = visible_text(page).lower()
    hints = (
        "captcha",
        "security check",
        "verificación de seguridad",
        "verificacion de seguridad",
        "completa la verificación",
        "complete the verification",
        "desliza para verificar",
        "slide to verify",
        "are you a robot",
        "soy humano",
    )
    selector_hints = (
        "iframe[src*='captcha']",
        "[id*='captcha' i]",
        "[class*='captcha' i]",
        "[id*='nc_']",
        "[class*='nc_']",
        "[class*='verify' i]",
    )
    selector_detected = False
    for selector in selector_hints:
        try:
            if page.locator(selector).count() > 0:
                selector_detected = True
                break
        except Exception:
            continue

    if selector_detected or any(hint in text for hint in hints):
        raise CaptchaDetectedError(
            "AliExpress solicitó una verificación humana/CAPTCHA; no se intentó resolver."
        )


def extract_price(page: Page) -> PriceResult:
    """Extract only product-price candidates, never generic coupon amounts."""
    ensure_not_captcha(page)

    title = "Producto AliExpress"
    try:
        title = clean_message(page.locator("h1").first.inner_text(timeout=4_000), 180)
    except Exception:
        try:
            title = clean_message(page.title(), 180)
        except Exception:
            pass

    # Prefer semantic metadata and the visible primary-price component.
    metadata_selectors = (
        "meta[property='product:price:amount']",
        "meta[itemprop='price']",
        "[itemprop='price']",
        "[data-pl='product-price']",
    )
    for selector in metadata_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            value = locator.get_attribute("content") or locator.get_attribute("value") or locator.inner_text()
            price = parse_price(value)
            if price is not None:
                return PriceResult(price=price, source=f"metadata:{selector}", title=title)
        except Exception:
            continue

    price_selectors = (
        "[class*='price--current']",
        "[class*='price-current']",
        "[class*='price--sale']",
        "[class*='price-sale']",
        "[class*='product-price']",
    )
    for selector in price_selectors:
        try:
            texts = page.locator(selector).all_inner_texts()
            price = price_from_texts(texts)
            if price is not None:
                return PriceResult(price=price, source=f"dom:{selector}", title=title)
        except Exception:
            continue

    # AliExpress places structured product data in JavaScript objects. Read it but
    # do not modify browser fingerprints or use anti-detection workarounds.
    structured_prices = page.evaluate(
        """() => {
          const roots = [window.runParams, window.__INITIAL_DATA__, window.__NEXT_DATA__];
          const paths = [
            ['data','priceComponent','discountPrice','minPrice'],
            ['data','priceComponent','discountPrice','maxPrice'],
            ['priceModule','minActivityAmount','value'],
            ['priceModule','formatedActivityPrice'],
            ['data','priceComponent','originalPrice','minPrice']
          ];
          const result = [];
          for (const root of roots) {
            if (!root) continue;
            for (const path of paths) {
              let node = root;
              for (const key of path) node = node && node[key];
              if (node !== undefined && node !== null) result.push(String(node));
            }
          }
          return result;
        }"""
    )
    price = price_from_texts(structured_prices or [])
    if price is not None:
        return PriceResult(price=price, source="structured-page-data", title=title)

    raise PriceNotFoundError("No se encontró un precio de producto fiable en la página.")


def capture_page(page: Optional[Page], label: str) -> Optional[Path]:
    """Persist a screenshot for notification and workflow diagnostics."""
    if page is None:
        return None
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / f"{label}.png"
    try:
        page.screenshot(path=str(path), full_page=True, timeout=20_000)
        print(f"[diagnóstico] Captura guardada en {path}")
        return path
    except Exception as exc:
        print(f"[diagnóstico] No se pudo capturar la página: {exc}")
        return None


def write_failure_note(error: Exception) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACTS_DIR / "failure.txt"
    path.write_text(
        f"timestamp_utc: {utc_now()}\nurl: {PRODUCT_URL}\nerror: {type(error).__name__}: {error}\n",
        encoding="utf-8",
    )
    return path


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise TrackerError(f"El estado {STATE_FILE} no es válido: {exc}") from exc


def save_state(price: float, title: str) -> None:
    state = {
        "price": round(price, 2),
        "currency": "EUR",
        "product_url": PRODUCT_URL,
        "product_title": title,
        "updated_at_utc": utc_now(),
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class WhatsAppNotifier:
    """Minimal official WhatsApp Cloud API client for approved templates."""

    def __init__(self) -> None:
        self.token = os.getenv("WA_ACCESS_TOKEN")
        self.phone_number_id = os.getenv("WA_PHONE_NUMBER_ID")
        self.recipient = os.getenv("WA_RECIPIENT")
        self.api_version = os.getenv("WA_API_VERSION", "v26.0")
        self.language = os.getenv("WA_TEMPLATE_LANGUAGE", "es")
        self.price_template = os.getenv("WA_TEMPLATE_PRICE", "aliexpress_price_alert")
        self.failure_template = os.getenv("WA_TEMPLATE_FAILURE", "aliexpress_tracker_error")

    @property
    def configured(self) -> bool:
        return bool(self.token and self.phone_number_id and self.recipient)

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}"

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> None:
        response = requests.post(
            f"{self.base_url}/{endpoint}",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            raise WhatsAppError(
                f"WhatsApp API respondió {response.status_code}: {clean_message(response.text, 500)}"
            )

    def _upload_image(self, screenshot: Path) -> str:
        with screenshot.open("rb") as handle:
            response = requests.post(
                f"{self.base_url}/media",
                headers=self.headers,
                data={"messaging_product": "whatsapp", "type": "image/png"},
                files={"file": (screenshot.name, handle, "image/png")},
                timeout=REQUEST_TIMEOUT,
            )
        if not response.ok:
            raise WhatsAppError(
                f"No se pudo subir la captura a WhatsApp ({response.status_code}): "
                f"{clean_message(response.text, 500)}"
            )
        media_id = response.json().get("id")
        if not media_id:
            raise WhatsAppError("WhatsApp no devolvió un identificador para la captura.")
        return str(media_id)

    def _send_template(
        self,
        template_name: str,
        body_values: list[str],
        screenshot: Optional[Path] = None,
    ) -> None:
        if not self.configured:
            print("[WhatsApp] No configurado: se omite la notificación.")
            return

        components: list[dict[str, Any]] = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": clean_message(value, 1024)}
                    for value in body_values
                ],
            }
        ]
        if screenshot is not None and screenshot.exists():
            media_id = self._upload_image(screenshot)
            components.insert(
                0,
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"id": media_id}}],
                },
            )

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.recipient,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": self.language},
                "components": components,
            },
        }
        self._post_json("messages", payload)
        print(f"[WhatsApp] Plantilla '{template_name}' aceptada por la API.")

    def send_price_drop(self, title: str, old_price: float, new_price: float) -> None:
        percentage = (old_price - new_price) / old_price * 100
        self._send_template(
            self.price_template,
            [
                title,
                f"{old_price:.2f}",
                f"{new_price:.2f}",
                f"-{percentage:.1f}%",
                PRODUCT_URL,
            ],
        )

    def send_failure(self, error: Exception, screenshot: Optional[Path]) -> None:
        self._send_template(
            self.failure_template,
            [
                PRODUCT_URL,
                f"{type(error).__name__}: {error}",
                utc_now(),
            ],
            screenshot=screenshot,
        )


def make_page(browser: Browser) -> Page:
    context = browser.new_context(
        locale="es-ES",
        timezone_id="Europe/Madrid",
        viewport={"width": 1440, "height": 1200},
        extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
    )
    context.add_cookies(
        [
            {
                "name": "aep_usuc_f",
                "value": "region=ES&b_locale=es_ES&c_tp=EUR",
                "domain": ".aliexpress.com",
                "path": "/",
            },
            {
                "name": "intl_locale",
                "value": "es_ES",
                "domain": ".aliexpress.com",
                "path": "/",
            },
        ]
    )
    return context.new_page()


def run_monitor() -> int:
    notifier = WhatsAppNotifier()
    page: Optional[Page] = None
    screenshot: Optional[Path] = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = make_page(browser)
                print(f"[monitor] Consultando {PRODUCT_URL}")
                response = page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
                if response is not None and response.status >= 400:
                    raise TrackerError(f"AliExpress devolvió HTTP {response.status}.")
                page.wait_for_timeout(2_500)
                result = extract_price(page)
                print(
                    f"[monitor] Precio: {result.price:.2f} EUR "
                    f"(origen: {result.source}; producto: {result.title})"
                )
            except Exception:
                # La página todavía está viva aquí; capturar antes de cerrar Chromium.
                screenshot = capture_page(page, "failure")
                raise
            finally:
                browser.close()

        state = load_state()
        old_price = parse_price(state.get("price"))
        save_state(result.price, result.title)

        if old_price is None:
            print("[monitor] Estado inicial creado; no se envía alerta.")
        elif result.price < old_price:
            print(f"[monitor] Bajada detectada: {old_price:.2f} -> {result.price:.2f} EUR")
            notifier.send_price_drop(result.title, old_price, result.price)
        elif result.price > old_price:
            print(f"[monitor] Subida detectada: {old_price:.2f} -> {result.price:.2f} EUR")
        else:
            print("[monitor] Sin cambios de precio.")
        return 0

    except Exception as error:
        screenshot = screenshot or capture_page(page, "failure")
        write_failure_note(error)
        print(f"[error] {type(error).__name__}: {error}", file=sys.stderr)
        traceback.print_exc()
        try:
            notifier.send_failure(error, screenshot)
        except Exception as notification_error:
            print(
                f"[error] También falló el aviso de WhatsApp: {notification_error}",
                file=sys.stderr,
            )
        return 2


def run_self_test() -> int:
    cases = {
        "277,39€": 277.39,
        "1.234,56 EUR": 1234.56,
        "99.90": 99.90,
        "": None,
    }
    for raw, expected in cases.items():
        assert parse_price(raw) == expected, f"parse_price({raw!r})"
    assert price_from_texts(["cupón -30,00€", "277,39€"]) == 277.39
    print("[self-test] OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(run_self_test())
    sys.exit(run_monitor())
