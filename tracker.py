#!/usr/bin/env python3
"""Monitor de precio de AliExpress con alertas por Telegram.

No intenta resolver ni eludir CAPTCHAs. Si la página presenta una verificación,
el proceso conserva una captura, intenta notificarla por Telegram y termina con
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
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

PRODUCT_URL = os.getenv(
    "PRODUCT_URL", "https://es.aliexpress.com/item/1005007999908066.html"
)
PRODUCT_URLS = tuple(
    dict.fromkeys(
        (
            PRODUCT_URL,
            PRODUCT_URL.replace("https://es.aliexpress.com", "https://www.aliexpress.com"),
            PRODUCT_URL.replace("https://es.aliexpress.com", "https://m.aliexpress.com"),
        )
    )
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


class TelegramError(TrackerError):
    """Raised when the Telegram Bot API declines a notification."""


@dataclass(frozen=True)
class PriceResult:
    price: float
    source: str
    title: str
    coupon: float = 0.0

    @property
    def effective_price(self) -> float:
        return max(0.0, self.price - self.coupon)


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


def detect_coupon(text: str) -> float:
    """Return the largest explicitly advertised EUR coupon amount.

    Only labels that identify a coupon/discount are considered; this avoids
    treating shipping, stock counts, ratings or unrelated prices as coupons.
    """
    candidates: list[float] = []
    coupon_pattern = re.compile(
        r"(?:cup[oó]n|coupon|descuento|ahorra|save|off)[^\n€$]{0,80}?"
        r"(?:[-−]\s*)?(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*€?",
        re.IGNORECASE,
    )
    for match in coupon_pattern.finditer(text):
        context = text[max(0, match.start() - 40) : match.end() + 40].lower()
        if any(word in context for word in ("entrega", "delivery", "tardía", "late delivery")):
            continue
        amount = parse_price(match.group(1))
        if amount is not None and 0 < amount < 10_000:
            candidates.append(amount)

    # AliExpress commonly renders a promotion as “-30,00€ en 239,00€”
    # without using the word coupon. A negative EUR amount is unambiguously a
    # discount, so include it while excluding ordinary positive prices.
    for match in re.finditer(
        r"[-−]\s*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*€",
        text,
        re.IGNORECASE,
    ):
        amount = parse_price(match.group(1))
        if amount is not None and 0 < amount < 10_000:
            candidates.append(amount)
    return max(candidates, default=0.0)


def page_price_candidates(page: Page) -> list[str]:
    """Collect price-like values from DOM, attributes, JSON and visible text."""
    values: list[str] = []
    selectors = (
        "meta[property='product:price:amount']",
        "meta[itemprop='price']",
        "[itemprop='price']",
        "[data-pl='product-price']",
        "[class*='price' i]",
        "[class*='amount' i]",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector)
            for index in range(min(locator.count(), 80)):
                element = locator.nth(index)
                value = (
                    element.get_attribute("content")
                    or element.get_attribute("value")
                    or element.inner_text(timeout=1_000)
                )
                if value:
                    values.append(value)
        except Exception:
            continue
    structured_values = page.evaluate(
        """() => {
          const roots = [window.runParams, window.__INITIAL_DATA__, window.__NEXT_DATA__];
          const out = [];
          const walk = (node, depth = 0) => {
            if (depth > 7 || node === null || node === undefined) return;
            if (typeof node === 'string' || typeof node === 'number') {
              const value = String(node);
              if (/\\d[.,]\\d{1,2}/.test(value) || /price|amount|coupon|discount|save|voucher/i.test(value)) out.push(value);
              return;
            }
            if (Array.isArray(node)) { for (const item of node) walk(item, depth + 1); return; }
            if (typeof node === 'object') {
              for (const [key, value] of Object.entries(node)) {
                if (/price|amount|coupon|discount|save|voucher|promotion/i.test(key)) walk(value, depth + 1);
              }
            }
          };
          for (const root of roots) walk(root);
          return out;
        }"""
    )
    values.extend(structured_values or [])
    return values


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
    """Extract product price, advertised coupon and effective price inputs."""
    ensure_not_captcha(page)

    title = "Producto AliExpress"
    try:
        title = clean_message(page.locator("h1").first.inner_text(timeout=4_000), 180)
    except Exception:
        try:
            title = clean_message(page.title(), 180)
        except Exception:
            pass

    body_text = visible_text(page)
    coupon = detect_coupon(body_text)

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
                return PriceResult(price=price, source=f"metadata:{selector}", title=title, coupon=coupon)
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
                return PriceResult(price=price, source=f"dom:{selector}", title=title, coupon=coupon)
        except Exception:
            continue

    # AliExpress places structured product data in JavaScript objects. Read it but
    # do not modify browser fingerprints or use anti-detection workarounds.
    structured_prices = page_price_candidates(page)
    price = price_from_texts(structured_prices)
    if price is not None:
        # The page text is a final fallback. It is intentionally used only
        # when a EUR marker occurs near a product-price/coupon context.
        return PriceResult(price=price, source="structured-or-dom-data", title=title, coupon=coupon)

    contextual_prices = re.findall(
        r"(?i)(?:precio|price|ahora|now|EUR|€)[^\n]{0,40}?(\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR)?",
        body_text,
    )
    price = price_from_texts(contextual_prices)
    if price is not None:
        return PriceResult(price=price, source="visible-text-context", title=title, coupon=coupon)

    visible_currency_prices = re.findall(
        r"(?<![\d-])(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(?:€|EUR)",
        body_text,
        re.IGNORECASE,
    )
    price = price_from_texts(visible_currency_prices)
    if price is not None:
        return PriceResult(price=price, source="visible-currency-text", title=title, coupon=coupon)

    raise PriceNotFoundError("No se encontró un precio de producto fiable en la página.")


def navigate_and_extract(page: Page) -> PriceResult:
    """Try equivalent official AliExpress hosts when one response is empty."""
    last_error: Optional[Exception] = None
    for url in PRODUCT_URLS:
        try:
            print(f"[monitor] Consultando {url}")
            response = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if response is not None and response.status >= 400:
                raise TrackerError(f"AliExpress devolvió HTTP {response.status}.")
            page.wait_for_timeout(2_500)
            if not visible_text(page).strip():
                raise PriceNotFoundError("La respuesta de AliExpress llegó vacía.")
            return extract_price(page)
        except Exception as error:
            last_error = error
            print(f"[monitor] Falló {url}: {error}; probando otra URL equivalente.")
    raise last_error or PriceNotFoundError("No se pudo leer la página de AliExpress.")


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


def save_state(price: float, title: str, display_price: Optional[float] = None, coupon: float = 0.0) -> None:
    state = {
        "price": round(price, 2),
        "currency": "EUR",
        "display_price": round(display_price if display_price is not None else price, 2),
        "coupon": round(coupon, 2),
        "product_url": PRODUCT_URL,
        "product_title": title,
        "updated_at_utc": utc_now(),
    }
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class TelegramNotifier:
    """Cliente mínimo de la Bot API de Telegram."""

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def _post(self, method: str, **kwargs: Any) -> None:
        response = requests.post(
            f"{self.base_url}/{method}",
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        if not response.ok:
            raise TelegramError(
                f"Telegram API respondió {response.status_code}: "
                f"{clean_message(response.text, 500)}"
            )
        payload = response.json()
        if not payload.get("ok", False):
            raise TelegramError(f"Telegram rechazó la petición: {clean_message(response.text, 500)}")

    def send_message(self, message: str) -> None:
        if not self.configured:
            print("[Telegram] No configurado: se omite la notificación.")
            return
        self._post(
            "sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": message,
                "disable_web_page_preview": "false",
            },
        )
        print("[Telegram] Mensaje enviado.")

    def send_photo(self, screenshot: Optional[Path], caption: str) -> None:
        if not self.configured:
            print("[Telegram] No configurado: se omite la notificación.")
            return
        if screenshot is None or not screenshot.exists():
            self.send_message(caption)
            return
        with screenshot.open("rb") as handle:
            self._post(
                "sendPhoto",
                data={"chat_id": self.chat_id, "caption": caption[:1024]},
                files={"photo": (screenshot.name, handle, "image/png")},
            )
        print("[Telegram] Captura enviada.")

    def send_price_drop(
        self,
        title: str,
        old_price: float,
        new_price: float,
        display_price: Optional[float] = None,
        coupon: float = 0.0,
    ) -> None:
        percentage = (old_price - new_price) / old_price * 100
        coupon_line = f"Cupón aplicado: -{coupon:.2f} €\n" if coupon > 0 else ""
        display_line = (
            f"Precio mostrado: {display_price:.2f} €\n"
            if display_price is not None and display_price != new_price
            else ""
        )
        self.send_message(
            "🚨 Bajada de precio detectada\n\n"
            f"Producto: {title}\n"
            f"Antes: {old_price:.2f} €\n"
            f"Ahora: {new_price:.2f} € (-{percentage:.1f}%)\n"
            f"{display_line}{coupon_line}\n"
            f"Ver producto: {PRODUCT_URL}"
        )

    def send_failure(self, error: Exception, screenshot: Optional[Path]) -> None:
        caption = (
            "⚠️ Error en el monitor de AliExpress\n\n"
            f"Tipo: {type(error).__name__}\n"
            f"Motivo: {clean_message(str(error), 700)}\n"
            f"URL: {PRODUCT_URL}\n"
            f"Hora UTC: {utc_now()}"
        )
        self.send_photo(screenshot, caption)


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


def make_local_page(playwright: Any) -> tuple[BrowserContext, Page]:
    """Open a persistent local Chromium profile for manual CAPTCHA handling."""
    profile_dir = Path(os.getenv("LOCAL_PROFILE_DIR", "aliexpress_profile"))
    profile_dir.mkdir(parents=True, exist_ok=True)
    headless = os.getenv("LOCAL_HEADLESS", "0").lower() in {"1", "true", "yes"}
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        locale="es-ES",
        timezone_id="Europe/Madrid",
        viewport={"width": 1440, "height": 1200},
        extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
        args=["--start-maximized"] if not headless else [],
    )
    return context, context.pages[0] if context.pages else context.new_page()


def run_monitor() -> int:
    notifier = TelegramNotifier()
    page: Optional[Page] = None
    screenshot: Optional[Path] = None
    try:
        with sync_playwright() as playwright:
            local_profile = os.getenv("LOCAL_PROFILE_DIR")
            browser: Optional[Browser] = None
            local_context: Optional[BrowserContext] = None
            try:
                if local_profile:
                    local_context, page = make_local_page(playwright)
                else:
                    browser = playwright.chromium.launch(headless=True)
                    page = make_page(browser)
                result = navigate_and_extract(page)
                print(
                    f"[monitor] Precio mostrado: {result.price:.2f} EUR; "
                    f"cupón: {result.coupon:.2f} EUR; "
                    f"precio efectivo: {result.effective_price:.2f} EUR "
                    f"(origen: {result.source}; producto: {result.title})"
                )
            except Exception:
                # La página todavía está viva aquí; capturar antes de cerrar Chromium.
                screenshot = capture_page(page, "failure")
                raise
            finally:
                if local_context is not None:
                    local_context.close()
                if browser is not None:
                    browser.close()

        state = load_state()
        old_price = parse_price(state.get("price"))
        effective_price = result.effective_price
        save_state(effective_price, result.title, result.price, result.coupon)

        if old_price is None:
            print("[monitor] Estado inicial creado; no se envía alerta.")
        elif effective_price < old_price:
            print(f"[monitor] Bajada efectiva detectada: {old_price:.2f} -> {effective_price:.2f} EUR")
            notifier.send_price_drop(result.title, old_price, effective_price, result.price, result.coupon)
        elif effective_price > old_price:
            print(f"[monitor] Subida efectiva detectada: {old_price:.2f} -> {effective_price:.2f} EUR")
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
                f"[error] También falló el aviso de Telegram: {notification_error}",
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
    assert detect_coupon("Cupón de 30,00€ en el producto") == 30.0
    assert detect_coupon("-30,00€ en 239,00€") == 30.0
    assert detect_coupon("Cupón de 1,00€ por entrega tardía") == 0.0
    assert PriceResult(277.39, "test", "Reloj", 30.0).effective_price == 247.39
    print("[self-test] OK")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(run_self_test())
    sys.exit(run_monitor())
