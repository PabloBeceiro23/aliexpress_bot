# Monitor de precio de AliExpress → Telegram

Este repositorio comprueba cada dos horas el precio en EUR del producto configurado y avisa por **Telegram Bot API** cuando el importe baja. El último precio confirmado se conserva en `price_state.json`, que se actualiza automáticamente mediante GitHub Actions.

> **Diseño ante CAPTCHA:** el monitor no intenta arrastrar controles, simular comportamiento humano ni sortear mecanismos de protección. Si AliExpress solicita una verificación o el precio no puede validarse, termina la ejecución, conserva una captura en el artefacto de GitHub Actions y manda esa captura a Telegram mediante el bot configurado. Así se obtiene evidencia del problema sin infringir las protecciones de la web.

## Funcionamiento

| Situación | Resultado |
|---|---|
| Primera lectura correcta | Guarda el precio inicial; no envía alerta. |
| El precio baja | Envía una alerta de Telegram con precio anterior, nuevo, porcentaje y enlace. |
| El precio sube o no cambia | Actualiza el estado si procede; no envía alerta. |
| CAPTCHA, HTTP anómalo, cambio de página o error de extracción | Genera `artifacts/failure.png` y `artifacts/failure.txt`, intenta mandarlos a Telegram y falla el workflow para hacerlo visible. |

La ejecución programada está definida en `.github/workflows/tracker.yml` con el cron `17 */2 * * *` (UTC). GitHub puede retrasar las ejecuciones programadas cuando hay alta demanda; el botón **Run workflow** permite lanzarlo manualmente.

## Configuración de Telegram

El workflow reutiliza los secretos de Telegram que ya estaban configurados en el repositorio:

| Secreto | Uso |
|---|---|
| `TELEGRAM_TOKEN` | Token del bot creado con BotFather. |
| `TELEGRAM_CHAT_ID` | Chat, grupo o canal que recibirá las alertas. |

No necesitas configurar otra API ni crear plantillas. En una bajada de precio se envía un mensaje de texto. Si aparece un CAPTCHA o cualquier otro error, se envía la captura mediante `sendPhoto`; además, GitHub Actions conserva `failure.png` y `failure.txt` como artefactos de diagnóstico.

Los mensajes proactivos de Telegram funcionan siempre que el bot tenga acceso al chat y el usuario haya iniciado conversación con él cuando sea necesario.

## Probarlo manualmente

1. Ve a la pestaña **Actions** del repositorio.
2. Abre el workflow **Monitor de precio AliExpress**.
3. Pulsa **Run workflow**.
4. Revisa el registro. Si hay CAPTCHA o fallo, descarga el artefacto `aliexpress-diagnostic-<id>` desde esa ejecución.

La primera ejecución correcta fijará el precio base en `price_state.json`. Para probar inmediatamente una alerta de bajada sin esperar al mercado, reduce temporalmente el valor `price` de ese archivo, lanza el workflow manualmente y vuelve a dejarlo en el valor correcto después de comprobar la notificación.

## Desarrollo local

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python tracker.py --self-test
python tracker.py
```

Sin los secretos de Telegram, el script sigue comprobando el precio y archivando errores, pero escribe `No configurado: se omite la notificación` en lugar de enviar mensajes.

## Limitaciones relevantes

AliExpress puede variar el precio según país, impuestos, cupón, variante, envío y sesión. El monitor utiliza la vista española, EUR y el precio principal mostrado, pero no incluye costes de envío ni promociones que exijan condiciones adicionales. Un CAPTCHA no se puede solucionar de forma fiable desde un runner no interactivo de GitHub Actions; este proyecto lo diagnostica y evidencia, no lo elude.
