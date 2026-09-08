@echo off
title Prueba de Concurrencia - Fase 5.6
cd /d "C:\Users\Zudokattsu\Documents\antigravity\agitated-mendeleev"

echo Verificando conexion con la API...
powershell -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2 | Out-Null } catch { Start-Process '.\venv\Scripts\uvicorn.exe' -ArgumentList 'app.main:app --port 8000 --host 127.0.0.1' -WindowStyle Hidden; Start-Sleep -Seconds 3 }"

echo.
.\venv\Scripts\python.exe scripts\test_concurrency_evidence.py

echo.
echo ==============================================================================
echo  Listo! Toma la captura de pantalla a esta ventana para tu entrega.
echo ==============================================================================
pause