@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Job Assistant

where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Criando ambiente virtual...
  python -m venv .venv
  if errorlevel 1 goto :erro
)

if not exist ".venv\.deps_ok" (
  echo [2/4] Instalando dependencias Python - so na primeira vez...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
  if errorlevel 1 goto :erro
  echo ok> ".venv\.deps_ok"
)

if not exist ".venv\.chromium_ok" (
  echo [3/4] Baixando o navegador usado na automacao - so na primeira vez...
  ".venv\Scripts\python.exe" -m playwright install chromium
  if errorlevel 1 goto :erro
  echo ok> ".venv\.chromium_ok"
)

if not exist ".env" copy ".env.example" ".env" >nul

if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo Node.js nao encontrado. Instale a versao LTS em https://nodejs.org e rode este arquivo de novo.
    pause
    exit /b 1
  )
  echo [4/4] Compilando a interface - so na primeira vez...
  pushd frontend
  call npm install
  if errorlevel 1 ( popd & goto :erro )
  call npm run build
  if errorlevel 1 ( popd & goto :erro )
  popd
)

echo.
echo ============================================================
echo   Job Assistant rodando em http://127.0.0.1:8000
echo   O navegador vai abrir sozinho. Para ENCERRAR, feche esta janela.
echo ============================================================
echo.
start "" /min cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
echo.
echo O servidor parou. Se apareceu erro de porta em uso, feche outras janelas do Job Assistant.
pause
exit /b 0

:erro
echo.
echo ERRO durante a preparacao. Leia a mensagem acima e me envie o texto.
pause
exit /b 1
