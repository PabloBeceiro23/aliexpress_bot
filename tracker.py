import os
import re
import requests
from playwright.sync_api import sync_playwright

# --- CONFIGURACIÓN ---
URL_PRODUCTO = "https://es.aliexpress.com/item/1005007999908066.html"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ARCHIVO_PRECIO = "precio_guardado.txt"

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Error: Faltan credenciales de Telegram.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[!] Error Telegram: {r.text}")
    except Exception as e:
        print(f"[!] Error enviando a Telegram: {e}")

def obtener_precio(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)  # Espera 4s a que carguen scripts dinámicos

    # Cerrar posibles popups o banners de cookies si aparecen
    for popup_selector in [
        "button:has-text('Aceptar')", 
        "button:has-text('Accept all')", 
        ".btn-accept", 
        ".pop-close-btn"
    ]:
        try:
            btn = page.locator(popup_selector).first
            if btn.is_visible(timeout=1500):
                btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

    # Selectores ampliados para capturar el precio actual
    selectores = [
        ".product-price-current",
        "[class*='price--current']",
        "[class*='product-price-value']",
        "span.es--wrap--y7V5bfe",
        ".uniform-banner-box-price",
        ".product-price-value",
        "[class*='price-current']"
    ]
    
    texto_precio = None
    for sel in selectores:
        try:
            elem = page.locator(sel).first
            if elem.is_visible(timeout=2000):
                texto_precio = elem.inner_text().strip()
                print(f"[*] Selector encontrado ({sel}): '{texto_precio}'")
                break
        except Exception:
            continue

    # Si no lo encuentra por selector, buscar en bloques de texto con símbolo € o EUR
    if not texto_precio:
        try:
            elem = page.locator("text=/\\d+[.,]\\d{2}\\s*(€|EUR)/").first
            if elem.is_visible(timeout=3000):
                texto_precio = elem.inner_text().strip()
                print(f"[*] Encontrado por texto general: '{texto_precio}'")
        except Exception:
            pass

    if not texto_precio:
        print("[!] No se encontró ningún elemento de precio. Tomando captura de pantalla...")
        page.screenshot(path="fallo_precio.png")
        return None

    # Limpiar texto (ej. "277,39€" -> 277.39)
    match = re.search(r"(\d+[\.,]\d+)", texto_precio)
    if match:
        valor_limpio = match.group(1).replace(",", ".")
        return float(valor_limpio)
    return None

def main():
    print("[*] Iniciando Playwright...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="es-ES",
            viewport={"width": 1920, "height": 1080}
        )
        
        # Cookies para España y moneda Euro
        context.add_cookies([
            {"name": "aep_usuc_f", "value": "region=ES&b_locale=es_ES&c_tp=EUR", "domain": ".aliexpress.com", "path": "/"},
            {"name": "intl_locale", "value": "es_ES", "domain": ".aliexpress.com", "path": "/"}
        ])

        page = context.new_page()

        print(f"[*] Navegando a la URL del producto...")
        precio_actual = obtener_precio(page, URL_PRODUCTO)
        browser.close()

        if precio_actual is None:
            print("[!] Salida prematura: precio_actual es None.")
            return

        print(f"[+] Precio procesado: {precio_actual} €")

        precio_previo = None
        if os.path.exists(ARCHIVO_PRECIO):
            try:
                with open(ARCHIVO_PRECIO, "r") as f:
                    contenido = f.read().strip()
                    if contenido:
                        precio_previo = float(contenido)
            except ValueError:
                pass

        if precio_previo is None:
            with open(ARCHIVO_PRECIO, "w") as f:
                f.write(str(precio_actual))
            enviar_telegram(f"🔍 *Monitor activado*\nPrecio inicial del producto: *{precio_actual:.2f} €*")
            print("[*] Primer registro guardado con éxito.")
        elif precio_actual < precio_previo:
            descuento = precio_previo - precio_actual
            porcentaje = (descuento / precio_previo) * 100
            msg = (
                f"🚨 *¡BAJADA DE PRECIO!* 🚨\n\n"
                f"• Antes: ~{precio_previo:.2f} €~\n"
                f"• Ahora: *{precio_actual:.2f} €* (-{porcentaje:.1f}%)\n\n"
                f"[Ver producto]({URL_PRODUCTO})"
            )
            enviar_telegram(msg)
            with open(ARCHIVO_PRECIO, "w") as f:
                f.write(str(precio_actual))
            print(f"[+] Notificación enviada.")
        elif precio_actual > precio_previo:
            with open(ARCHIVO_PRECIO, "w") as f:
                f.write(str(precio_actual))
            print(f"[*] El precio subió a {precio_actual} €. Registro actualizado.")
        else:
            print("[*] El precio no ha cambiado.")

if __name__ == "__main__":
    main()
