@echo off
REM Inicia o mock do Aurora (streams LSL 'Aurora' e 'Trigger').
REM %~dp0 = pasta onde este .bat esta, entao funciona mesmo se voce
REM mover a pasta do projeto inteira para outro lugar/PC.
cd /d "%~dp0"
"C:\Program Files\PsychoPy\python.exe" mock_aurora_lsl.py
echo.
echo ------------------------------------------------------------
echo O mock parou ou fechou. Revise a mensagem acima se foi erro.
echo ------------------------------------------------------------
pause
