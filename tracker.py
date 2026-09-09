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
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] Error enviando a Telegram: {e}")

def enviar_foto_telegram(ruta_foto, caption=""):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID or not os.path.exists(ruta_foto):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(ruta_foto, "rb") as foto:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption}, files={"photo": foto}, timeout=20)
    except Exception as e:
        print(f"[!] Error enviando foto a Telegram: {e}")

def intentar_resolver_slider(page):
    # Selectores típicos del botón del deslizador de Alibaba/AliExpress
    slider_selectors = [
        "#nc_1_n1z",
        ".btn_slide",
        "span[class*='btn_slide']",
        ".nc-lang-cnt"
    ]
    
    for sel in slider_selectors:
        try:
            slider = page.locator(sel).first
            if slider.is_visible(timeout=3000):
                print("[*] Deslizador antibot detectado. Intentando arrastrar...")
                box = slider.bounding_box()
                if box:
                    # Mover el ratón al centro del deslizador
                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    page.mouse.down()
                    
                    # Simular un arrastre humano hacia la derecha en varios pasos
                    destino_x = box["x"] + 350
                    pasos = 25
                    for i in range(1, pasos + 1):
                        intermedio_x = box["x"] + (destino_x - box["x"]) * (i / pasos)
                        page.mouse.move(intermedio_x, box["y"] + box["height"] / 2)
                        page.wait_for_timeout(20)
                    
                    page.mouse.up()
                    page.wait_for_timeout(3000)
                    print("[*] Deslizador arrastrado. Continuando...")
                    return True
        except Exception as e:
            print(f"[!] Error al manipular el deslizador: {e}")
            continue
    return False

def extraer_precio_pagina(page):
    # Intentar extraer el precio desde los objetos JSON nativos de AliExpress en el DOM
    try:
        precio_json = page.evaluate("""() => {
            const data = window.runParams || window.__INITIAL_DATA__ || {};
            if (data?.data?.priceComponent?.discountPrice?.minPrice) {
                return data.data.priceComponent.discountPrice.minPrice;
            }
            if (data?.priceModule?.minActivityAmount?.value) {
                return data.priceModule.minActivityAmount.value;
            }
            return null;
        }""")
        if precio_json:
            print(f"[*] Precio extraído de JavaScript interno: {precio_json}")
            return float(precio_json)
    except Exception:
        pass

    # Selectores visuales habituales
    selectores = [
        ".product-price-current",
        "[class*='price--current']",
        "[class*='product-price-value']",
        "span.es--wrap--y7V5bfe",
        ".uniform-banner-box-price",
        ".product-price-value",
        "[class*='price-current']",
        "span[class*='Price--current']"
    ]
    
    for sel in selectores:
        try:
            elem = page.locator(sel).first
            if elem.is_visible(timeout=2000):
                texto = elem.inner_text().strip()
                match = re.search(r"(\d+[\.,]\d+)", texto)
                if match:
                    print(f"[*] Encontrado por selector ({sel}): {texto}")
                    return float(match.group(1).replace(",", "."))
        except Exception:
            continue

    # Respaldo: buscar patrones de moneda (€ o EUR)
    try:
        elementos_moneda = page.locator("text=/\\d+[.,]\\d{2}\\s*(€|EUR)/").all()
        for el in elementos_moneda:
            if el.is_visible():
                txt = el.inner_text().strip()
                match = re.search(r"(\d+[\.,]\d+)", txt)
                if match:
                    print(f"[*] Encontrado por patrón de texto: {txt}")
                    return float(match.group(1).replace(",", "."))
    except Exception:
        pass

    return None

def main():
    print("[*] Iniciando Playwright con evasión de detección...")
    with sync_playwright() as p:
        # Argumentos para evitar que AliExpress detecte Chromium como headless/bot
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="es-ES",
            viewport={"width": 1920, "height": 1080}
        )

        # Inyectar script para ocultar webdriver a nivel de navegador
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Cookies para España y Euro
        context.add_cookies([
            {"name": "aep_usuc_f", "value": "region=ES&b_locale=es_ES&c_tp=EUR", "domain": ".aliexpress.com", "path": "/"},
            {"name": "intl_locale", "value": "es_ES", "domain": ".aliexpress.com", "path": "/"}
        ])

        print(f"[*] Navegando a la URL del producto...")
        page.goto(URL_PRODUCTO, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)

        # Si aparece el captcha deslizante, lo arrastramos
        intentar_resolver_slider(page)

        precio_actual = extraer_precio_pagina(page)

        # Si aparece el modal de cookies o bienvenida, intentar cerrarlo
        for sel in ["button:has-text('Aceptar')", "button:has-text('Accept all')", ".btn-accept", ".pop-close-btn"]:
            try:
                b = page.locator(sel).first
                if b.is_visible(timeout=1000):
                    b.click()
            except Exception:
                pass

        precio_actual = extraer_precio_pagina(page)

        if precio_actual is None:
            print("[!] No se encontró el precio. Guardando captura de pantalla y enviando por Telegram...")
            page.screenshot(path="captura_fallo.png", full_page=False)
            browser.close()
            enviar_foto_telegram("captura_fallo.png", "⚠️ El bot no pudo encontrar el precio. Esto es lo que ve el navegador:")
            return

        browser.close()
        print(f"[+] Precio obtenido: {precio_actual} €")

        # Comparar con el precio guardado
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
            enviar_telegram(f"🔍 *Monitor activado*\nPrecio inicial: *{precio_actual:.2f} €*")
            print("[*] Primer registro guardado.")
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
