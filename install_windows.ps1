$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host 'No se encontró Python. Instala Python 3.11 o superior desde https://www.python.org/downloads/windows/' -ForegroundColor Red
    exit 1
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
}

.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium

New-Item -ItemType Directory -Force -Path 'artifacts' | Out-Null
New-Item -ItemType Directory -Force -Path 'aliexpress_profile' | Out-Null

Write-Host ''
Write-Host 'Instalación terminada.' -ForegroundColor Green
Write-Host 'La primera ejecución abrirá Chromium visible. Inicia sesión en AliExpress y resuelve el CAPTCHA manualmente si aparece.'
Write-Host 'Después puedes cerrar esa ventana: el perfil quedará guardado en aliexpress_profile.'
Write-Host ''
Write-Host 'Para probar una consulta:'
Write-Host '  .venv\Scripts\python.exe tracker.py'
Write-Host ''
Write-Host 'Para dejar el monitor ejecutándose cada dos horas:'
Write-Host '  .venv\Scripts\python.exe run_local.py'
