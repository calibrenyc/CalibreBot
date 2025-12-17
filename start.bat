@echo off

:: Check if .env exists
if not exist .env (
    echo Error: .env file not found!
    echo Please copy .env.example to .env and fill in your DISCORD_TOKEN.
    pause
    exit /b
)

:: Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

:: Run the bot
echo Starting the bot...
python bot.py
pause
