"""Integrated server test — server and client in same event loop."""
import asyncio, json, sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from aiohttp import web
from server.world import World
from server.ws_handler import WSManager
from server.http_routes import handle_register, handle_status
from server.config import TICK_INTERVAL


async def test_integrated():
    server_world = World(seed=42)
    server_ws = WSManager(server_world)
    _tick = 0
    _running = True
    results_sent = asyncio.Event()

    async def tick_loop():
        nonlocal _tick
        while _running:
            server_world.start_tick(_tick)
            tick_frame = {'type': 'tick', 'tick': _tick, 'messages': [
                {'role': 'system', 'content': f'Tick {_tick}'}
            ]}
            await server_ws.broadcast_tick(tick_frame)
            await asyncio.sleep(TICK_INTERVAL)
            actions = server_world.get_actions_for_tick(_tick)
            if actions:
                print(f'  [TickLoop] T{_tick}: {sum(len(v) for v in actions.values())} actions from {len(actions)} agents')
            results = server_world.settle_actions(_tick, actions)
            for aid, res in results.items():
                print(f'  [TickLoop] Sending {len(res)} results to {aid[:12]}...')
                await server_ws.send_result(aid, _tick, res)
                results_sent.set()
            server_world.advance_world()
            _tick += 1

    app = web.Application()
    app['world'] = server_world
    app.router.add_post('/api/v1/auth/register', handle_register)
    app.router.add_get('/api/v1/status', handle_status)
    app.router.add_get('/ws/game', server_ws.handle_connection)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8767)
    await site.start()
    print('Server started on port 8767')

    tick_task = asyncio.create_task(tick_loop())
    await asyncio.sleep(0.5)  # let tick loop start

    try:
        import requests, websockets

        # Register
        resp = requests.post('http://localhost:8767/api/v1/auth/register', json={
            'agent_name': 'TestBot', 'chassis': {
                'head': {'tier': 'high'}, 'torso': {'tier': 'mid'}, 'locomotion': {'tier': 'low'}
            }
        })
        data = resp.json()
        token = data['game_token']
        print(f'Agent registered: {data["agent_id"]}')

        # Connect
        ws = await websockets.connect(f'ws://localhost:8767/ws/game?token={token}')
        session_raw = await ws.recv()
        session = json.loads(session_raw)
        print(f'Frame 1: type={session["type"]}')
        assert session["type"] == "session"

        await ws.send(json.dumps({'type': 'ready'}))

        # Wait for tick
        tick_raw = await ws.recv()
        tick = json.loads(tick_raw)
        print(f'Frame 2: type={tick["type"]} tick={tick["tick"]}')
        assert tick["type"] == "tick"

        # Send actions
        await ws.send(json.dumps({
            'type': 'actions', 'tick': tick['tick'],
            'actions': [{'type': 'inspect', 'target': 'inventory'}],
        }))
        print(f'Sent actions for tick {tick["tick"]}')

        # Wait for result (with timeout)
        result = None
        for i in range(10):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                frame = json.loads(raw)
                print(f'Frame {i+3}: type={frame["type"]}')
                if frame["type"] == "result":
                    result = frame
                    print(f'  ✓ Got result: {len(frame["results"])} action results')
                    for r in frame["results"]:
                        print(f'    {r["type"]}: success={r["success"]} {r.get("detail","")}')
                    break
                elif frame["type"] == "error":
                    print(f'  ✗ Error: {frame}')
            except asyncio.TimeoutError:
                print(f'  Timeout waiting for frame {i+3}')
                break

        if result:
            print('\n✅ Integration test PASSED - Server properly returns result frames')
        else:
            print('\n❌ Integration test FAILED - No result frame received')
            print(f'  Remaining actions in collected: {list(server_world.collected_actions.keys())}')

        await ws.close()
    finally:
        _running = False
        tick_task.cancel()
        await asyncio.sleep(0.5)
        await runner.cleanup()
        print('Server stopped')

asyncio.run(test_integrated())
