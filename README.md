# Monitor de precio de AliExpress → WhatsApp

Este repositorio comprueba cada dos horas el precio en EUR del producto configurado y avisa por **WhatsApp Business Platform (Cloud API)** cuando el importe baja. El último precio confirmado se conserva en `price_state.json`, que se actualiza automáticamente mediante GitHub Actions.

> **Diseño ante CAPTCHA:** el monitor no intenta arrastrar controles, simular comportamiento humano ni sortear mecanismos de protección. Si AliExpress solicita una verificación o el precio no puede validarse, termina la ejecución, conserva una captura en el artefacto de GitHub Actions y manda esa captura a WhatsApp mediante una plantilla aprobada. Así se obtiene evidencia del problema sin infringir las protecciones de la web.

## Funcionamiento

| Situación | Resultado |
|---|---|
| Primera lectura correcta | Guarda el precio inicial; no envía alerta. |
| El precio baja | Envía una alerta de WhatsApp con precio anterior, nuevo, porcentaje y enlace. |
| El precio sube o no cambia | Actualiza el estado si procede; no envía alerta. |
| CAPTCHA, HTTP anómalo, cambio de página o error de extracción | Genera `artifacts/failure.png` y `artifacts/failure.txt`, intenta mandarlos a WhatsApp y falla el workflow para hacerlo visible. |

La ejecución programada está definida en `.github/workflows/tracker.yml` con el cron `17 */2 * * *` (UTC). GitHub puede retrasar las ejecuciones programadas cuando hay alta demanda; el botón **Run workflow** permite lanzarlo manualmente.

## Configurar WhatsApp Cloud API

Las alertas proactivas de WhatsApp fuera de la ventana de atención de 24 horas requieren **plantillas aprobadas** y que el destinatario haya aceptado recibir mensajes. El script usa la API oficial de Meta, no una sesión de WhatsApp Web.

En WhatsApp Manager, crea y aprueba estas dos plantillas con idioma `es` (puedes usar otros nombres si luego defines las variables del repositorio):

### 1. `aliexpress_price_alert`

Tipo recomendado: **Utility**. Cabecera: ninguna. Cuerpo, con cinco variables:

```text
Bajada de precio detectada
Producto: {{1}}
Antes: {{2}} €
Ahora: {{3}} € ({{4}})
Ver producto: {{5}}
```

### 2. `aliexpress_tracker_error`

Tipo recomendado: **Utility**. La cabecera debe ser de tipo **Imagen**. Cuerpo, con tres variables:

```text
El monitor de AliExpress necesita revisión.
Producto: {{1}}
Motivo: {{2}}
Hora UTC: {{3}}
```

El script sube la captura a Meta y la usa como cabecera de la segunda plantilla. Si la plantilla no incluye una cabecera de imagen, Meta rechazará ese aviso, pero la captura seguirá descargable como artefacto de GitHub Actions.

## Secretos y variables de GitHub

Abre **Settings → Secrets and variables → Actions** en el repositorio y crea los tres secretos siguientes. No guardes estas credenciales en archivos ni las pegues en el código.

| Tipo | Nombre | Valor |
|---|---|---|
| Secret | `WA_ACCESS_TOKEN` | Token de acceso de Meta con permisos para WhatsApp Cloud API. Para uso estable, utiliza un token de usuario del sistema, no el temporal de prueba. |
| Secret | `WA_PHONE_NUMBER_ID` | ID numérico del número de teléfono de WhatsApp Business configurado en Meta. |
| Secret | `WA_RECIPIENT` | Número de WhatsApp que recibirá las alertas, con prefijo internacional, por ejemplo `+34600111222`. Debe haber dado opt-in. |
| Variable (opcional) | `WA_TEMPLATE_PRICE` | Nombre de la plantilla de alerta; por defecto `aliexpress_price_alert`. |
| Variable (opcional) | `WA_TEMPLATE_FAILURE` | Nombre de la plantilla de error; por defecto `aliexpress_tracker_error`. |
| Variable (opcional) | `WA_TEMPLATE_LANGUAGE` | Código de idioma de las plantillas; por defecto `es`. |

También puedes cargarlos desde una terminal autenticada con GitHub CLI, que pedirá cada valor de forma segura:

```bash
gh secret set WA_ACCESS_TOKEN --repo PabloBeceiro23/aliexpress_bot
gh secret set WA_PHONE_NUMBER_ID --repo PabloBeceiro23/aliexpress_bot
gh secret set WA_RECIPIENT --repo PabloBeceiro23/aliexpress_bot

gh variable set WA_TEMPLATE_PRICE --body aliexpress_price_alert --repo PabloBeceiro23/aliexpress_bot
gh variable set WA_TEMPLATE_FAILURE --body aliexpress_tracker_error --repo PabloBeceiro23/aliexpress_bot
gh variable set WA_TEMPLATE_LANGUAGE --body es --repo PabloBeceiro23/aliexpress_bot
```

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

Sin los secretos de WhatsApp, el script sigue comprobando el precio y archivando errores, pero escribe `No configurado: se omite la notificación` en lugar de enviar mensajes.

## Limitaciones relevantes

AliExpress puede variar el precio según país, impuestos, cupón, variante, envío y sesión. El monitor utiliza la vista española, EUR y el precio principal mostrado, pero no incluye costes de envío ni promociones que exijan condiciones adicionales. Un CAPTCHA no se puede solucionar de forma fiable desde un runner no interactivo de GitHub Actions; este proyecto lo diagnostica y evidencia, no lo elude.
