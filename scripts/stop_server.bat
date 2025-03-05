@echo off
echo Stopping Okta AI Agent Server...

:: Find process using port 8001
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8001"') do (
    echo Found process: %%p
    :: Attempt graceful shutdown first
    taskkill /PID %%p /T /F
    if errorlevel 1 (
        echo Warning: Could not terminate process %%p
    ) else (
        echo Successfully terminated process %%p
    )
)

:: Double check if port is clear
netstat -ano | findstr ":8001" > nul
if errorlevel 1 (
    echo Server stopped successfully
) else (
    echo Warning: Port 8001 still in use
)