#!/bin/bash

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Error: .env file not found!"
    echo "Please copy .env.example to .env and fill in your DISCORD_TOKEN."
    exit 1
fi

while true; do
    # Install dependencies
    echo "Installing dependencies..."
    python3 -m pip install -r requirements.txt

    # Run the bot
    echo "Starting the bot..."
    python3 bot.py

    echo "Bot stopped. Restarting in 5 seconds..."
    sleep 5
done
