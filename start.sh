#!/bin/bash
# Ember Protocol MVP — Start Script
# Starts the game server and web frontend

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🔥 Ember Protocol MVP — Starting..."
echo ""

# Start game server
echo "Starting game server on :8765..."
cd "$DIR"
python3 -m server.main --port 8765 --data-dir ./data &
SERVER_PID=$!
sleep 3

# Check server
if curl -s http://localhost:8765/api/v1/status > /dev/null 2>&1; then
    echo "✅ Game server running (PID $SERVER_PID)"
else
    echo "❌ Game server failed to start"
    exit 1
fi

# Start web frontend
echo "Starting web frontend on :5173..."
cd "$DIR/web"
npx vite --port 5173 &
WEB_PID=$!
sleep 2

echo ""
echo "============================================"
echo "🔥 Ember Protocol MVP — Ready!"
echo ""
echo "  Game API:     http://localhost:8765"
echo "  Web Frontend: http://localhost:5173"
echo "  WebSocket:    ws://localhost:8765/ws/game"
echo ""
echo "  Register:     http://localhost:5173 (click '+ 创建角色')"
echo "  Agent Test:   python3 agent/ember_agent.py"
echo "  Run Tests:    python3 -m pytest tests/"
echo ""
echo "Press Ctrl+C to stop all services"
echo "============================================"

trap "kill $SERVER_PID $WEB_PID 2>/dev/null; echo 'Stopped.'" EXIT
wait
