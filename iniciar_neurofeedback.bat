@echo off
REM Inicia a janela de neurofeedback (run_neurofeedback.py).
REM Requer o mock (ou o Aurora real, conforme REPLAY_MODE em nf_config.py)
REM ja rodando antes de abrir este.
cd /d "%~dp0"
"C:\Program Files\PsychoPy\python.exe" run_neurofeedback.py --duration 90
echo.
echo ------------------------------------------------------------
echo A sessao terminou ou fechou. Revise a mensagem acima se foi erro.
echo ------------------------------------------------------------
pause
