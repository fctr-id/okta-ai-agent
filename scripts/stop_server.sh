#!/bin/bash
echo "Stopping Okta AI Agent Server..."

# Find process using port 8001
PID=$(lsof -ti:8001)

if [ ! -z "$PID" ]; then
    echo "Found process: $PID"
    # Try graceful shutdown first
    kill $PID
    sleep 2
    
    # Check if process still exists
    if ps -p $PID > /dev/null; then
        echo "Force killing process..."
        kill -9 $PID
    fi
    
    echo "Server stopped successfully"
else
    echo "No process found running on port 8001"
fi

# Verify port is free
if lsof -i:8001; then
    echo "Warning: Port 8001 still in use"
else
    echo "Port 8001 is clear"
fi