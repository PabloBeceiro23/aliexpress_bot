# Ejecutar el monitor localmente en Windows

Esta versión ejecuta Chromium en el PC y conserva un perfil local en `aliexpress_profile`. Es diferente del runner efímero de GitHub Actions: puedes iniciar sesión manualmente y resolver un CAPTCHA desde la ventana del navegador. No se exportan cookies a GitHub ni se intenta resolver el CAPTCHA automáticamente.

## Instalación

1. Instala **Python 3.11 o superior** desde [python.org](https://www.python.org/downloads/windows/). Durante la instalación, activa **Add Python to PATH**.
2. Descarga este repositorio como ZIP y descomprímelo en una carpeta fija, por ejemplo `C:\AliExpressBot`.
3. Abre PowerShell en esa carpeta.
4. Si Windows bloquea la ejecución de scripts, permite únicamente esta sesión:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

5. Ejecuta el instalador:

```powershell
.\install_windows.ps1
```

6. Ejecuta una primera comprobación visible:

```powershell
.venv\Scripts\python.exe tracker.py
```

Se abrirá Chromium. Inicia sesión en AliExpress si quieres usar tu cuenta y resuelve manualmente cualquier CAPTCHA. El perfil se guardará en `aliexpress_profile`. No borres esa carpeta si quieres conservar la sesión.

## Ejecutarlo cada dos horas

Para probarlo en primer plano:

```powershell
.venv\Scripts\python.exe run_local.py
```

Para ocultar la ventana de consola:

```powershell
wscript.exe .\run_local_hidden.vbs
```

El proceso queda ejecutándose y hace una comprobación cada 7.200 segundos. Para detenerlo desde PowerShell:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_local.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }
```

Para que arranque al iniciar Windows, crea un acceso directo a `run_local_hidden.vbs` dentro de:

```text
Win + R → shell:startup
```

El PC debe permanecer encendido, conectado a Internet y sin suspenderse. La ventana de Chromium puede estar minimizada, pero no conviene usar el mismo perfil de AliExpress simultáneamente en otro Chromium.

## Telegram

El ejecutor local reutiliza las mismas variables de entorno que el workflow:

```powershell
$env:TELEGRAM_TOKEN = 'tu_token'
$env:TELEGRAM_CHAT_ID = 'tu_chat_id'
```

Para no escribirlas cada vez, configúralas como variables de entorno de usuario desde Windows o crea un archivo `.env` solo si añades después una librería para cargarlo. No subas tokens a GitHub, al repositorio ni a este directorio.

Si ya tienes las credenciales configuradas únicamente como **Secrets de GitHub**, esas credenciales no se descargan al PC automáticamente: GitHub no permite leerlas desde el repositorio. Tendrás que introducirlas localmente una vez.

## Qué hace con un CAPTCHA

Cuando aparece un CAPTCHA, el script guarda `artifacts/failure.png` y `artifacts/failure.txt`, intenta enviar la captura por Telegram y termina esa comprobación. El proceso principal espera dos horas y vuelve a intentarlo. Si el navegador está visible, puedes ejecutar `tracker.py` manualmente, resolver el CAPTCHA y dejar guardado el perfil para posteriores consultas.

El monitor no automatiza clics, deslizamientos ni resolución de CAPTCHA.
