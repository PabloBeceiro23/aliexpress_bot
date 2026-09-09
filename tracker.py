import os
import re
import requests
from playwright.sync_api import sync_playwright

# --- CONFIGURACIÓN ---
# Pega aquí el enlace de tu producto entre las comillas:
URL_PRODUCTO = "https://es.aliexpress.com/item/1005007999908066.html"

# Leemos las credenciales guardadas en Secrets de GitHub
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
ARCHIVO_PRECIO = "precio_guardado.txt"

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[!] Error: No se han encontrado las variables TELEGRAM_TOKEN o TELEGRAM_CHAT_ID.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[!] Error de Telegram API: {r.text}")
    except Exception as e:
        print(f"[!] Error de conexión enviando a Telegram: {e}")

def obtener_precio(page, url):
    # Abrimos la página simulando una pantalla real
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    
    # Selectores donde suele estar el precio en AliExpress
    selectores = [
        ".product-price-current",
        "[class*='price--current']",
        "[class*='product-price-value']",
        "span.es--wrap--y7V5bfe",
        ".uniform-banner-box-price"
    ]
    
    texto_precio = None
    for sel in selectores:
        try:
            elem = page.wait_for_selector(sel, timeout=7000)
            if elem and elem.is_visible():
                texto_precio = elem.inner_text().strip()
                break
        except Exception:
            continue

    # Si no funciona por selector de clase, busca patrones de moneda (€ / $) en pantalla
    if not texto_precio:
        try:
            texto_precio = page.locator("text=/\\d+[.,]\\d{2}\\s*(€|\\$)/").first.inner_text().strip()
        except Exception:
            return None

    # Extrae el número decimal (ejemplo: '14,99 €' -> 14.99)
    match = re.search(r"(\d+[\.,]\d+)", texto_precio)
    if match:
        valor_limpio = match.group(1).replace(",", ".")
        return float(valor_limpio)
    return None

def main():
    print("[*] Iniciando navegador...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="es-ES"
        )
        page = context.new_page()

        print(f"[*] Comprobando precio en: {URL_PRODUCTO}")
        precio_actual = obtener_precio(page, URL_PRODUCTO)
        browser.close()

        if precio_actual is None:
            print("[!] No se ha podido extraer el precio de la página.")
            return

        print(f"[+] Precio actual detectado: {precio_actual} €")

        # Comprobamos el precio previo guardado en el repositorio
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
            # Primera ejecución: registra el precio base
            with open(ARCHIVO_PRECIO, "w") as f:
                f.write(str(precio_actual))
            enviar_telegram(f"🔍 *Monitor activado*\nPrecio inicial del producto: *{precio_actual:.2f} €*")
            print("[*] Primer registro guardado.")
        elif precio_actual < precio_previo:
            # ¡Bajó de precio!
            descuento = precio_previo - precio_actual
            porcentaje = (descuento / precio_previo) * 100
            msg = (
                f"🚨 *¡BAJADA DE PRECIO!* 🚨\n\n"
                f"• Antes: ~{precio_previo:.2f} €~\n"
                f"• Ahora: *{precio_actual:.2f} €* (-{porcentaje:.1f}%)\n\n"
                f"[Haz clic aquí para ver el producto]({URL_PRODUCTO})"
            )
            enviar_telegram(msg)
            with open(ARCHIVO_PRECIO, "w") as f:
                f.write(str(precio_actual))
            print(f"[+] Notificación de bajada enviada: {precio_actual} €")
        elif precio_actual > precio_previo:
            # Si subió, actualizamos el registro sin enviar alerta para no molestar
            with open(ARCHIVO_PRECIO, "w") as f:
                f.write(str(precio_actual))
            print(f"[*] El precio subió a {precio_actual} €. Registro actualizado.")
        else:
            print("[*] El precio no ha cambiado.")

if __name__ == "__main__":
    main()
