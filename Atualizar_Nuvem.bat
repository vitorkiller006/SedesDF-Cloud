@echo off
echo =======================================
echo   ATUALIZANDO NUVEM (GITHUB) - SEDES DF
echo =======================================
cd /d "%~dp0"
git add .
git commit -m "Atualizacao automatica: %date% %time%"
git push origin master
echo.
echo Processo concluido! O Streamlit Cloud vai atualizar o site em alguns segundos.
pause
