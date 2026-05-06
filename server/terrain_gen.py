"""Ember Protocol — Terrain Generation (adapted from scripts/generate_terrain.py)"""
from __future__ import annotations
import random
import numpy as np
from PIL import Image
from collections import deque, Counter
from .config import MAP_WIDTH as W, MAP_HEIGHT as H, CENTER_Y, MAP_SEED
from .models import Terrain

DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]
H1, H2 = 374761393, 668265263


def _seed_rng(seed: int):
    random.seed(seed)
    np.random.seed(seed + 1)


def fbm(scale: float, octaves: int = 3, seed: int = 0) -> np.ndarray:
    rng = np.random.RandomState(seed)
    result = np.zeros((H, W), dtype=np.float32)
    amp, total = 1.0, 0.0
    for _ in range(octaves):
        gw, gh = max(2, int(W * scale)), max(2, int(H * scale))
        coarse = rng.rand(gh, gw).astype(np.float32)
        img = Image.fromarray((coarse * 255).astype(np.uint8))
        layer = np.array(img.resize((W, H), Image.BILINEAR), dtype=np.float32) / 255.0
        result += layer * amp
        total += amp
        amp *= 0.5
        scale *= 2.0
    return result / total


def generate_terrain(seed: int = MAP_SEED) -> dict:
    """Generate full world terrain and return as dict.

    Returns dict with keys:
        l1_terrain: np.ndarray of str (flat/sand/rock/water/trench)
        l2_type: np.ndarray of str (stone/ashbush/greytree/wallmoss/floor/rubble or '')
        stone_amount: np.ndarray of int
        ore_type: np.ndarray of str
        ore_amount: np.ndarray of int
        ore_exposed: np.ndarray of bool
        stone_depth: np.ndarray of int
        veg_yield: np.ndarray of int
        tiles: list of Tile objects (200x200 serialized)
    """
    _seed_rng(seed)
    rock_field = fbm(0.04, octaves=3, seed=42)
    detail = fbm(0.18, octaves=2, seed=99)
    moist = fbm(0.05, octaves=2, seed=77)

    l1_terrain = np.full((H, W), '', dtype=object)
    l2_type = np.full((H, W), '', dtype=object)
    stone_amount = np.zeros((H, W), dtype=int)
    ore_type = np.full((H, W), '', dtype=object)
    ore_amount = np.zeros((H, W), dtype=int)

    # Phase 1: L1 terrain + L2 Stone
    for y in range(H):
        w = abs(y - CENTER_Y) / CENTER_Y
        for x in range(W):
            threshold = 0.70 - w * 0.35 + (detail[y, x] - 0.5) * 0.06
            if rock_field[y, x] > threshold:
                l1_terrain[y, x] = 'rock'  # Stone always on rock bedrock
                l2_type[y, x] = 'stone'
                stone_amount[y, x] = max(3, min(12, int(5 + w * 4 + (rock_field[y, x] - threshold) * 10)))
            else:
                m = moist[y, x]
                if m > 0.74 and w > 0.12 and rock_field[y, x] < 0.25:
                    l1_terrain[y, x] = 'water' if m > 0.80 else 'trench'
                elif m > 0.50:
                    l1_terrain[y, x] = 'sand'
                else:
                    l1_terrain[y, x] = 'flat'
                l2_type[y, x] = ''
                stone_amount[y, x] = 0

    # Thin Stone removal
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] == 'stone' and stone_amount[y, x] <= 4:
                l2_type[y, x] = ''
                stone_amount[y, x] = 0

    # Cleanup: remove isolated Stone, fill surrounded pockets
    nt = l2_type.copy()
    for y in range(H):
        for x in range(W):
            nb = sum(1 for dy, dx in DIRS
                     if 0 <= y + dy < H and 0 <= x + dx < W
                     and l2_type[y + dy, x + dx] == 'stone')
            if l2_type[y, x] == 'stone' and nb == 0:
                nt[y, x] = ''
                stone_amount[y, x] = 0
                l1_terrain[y, x] = 'rock'
            elif l2_type[y, x] != 'stone' and nb == 4:
                nt[y, x] = 'stone'
                w = abs(y - CENTER_Y) / CENTER_Y
                stone_amount[y, x] = max(3, int(4 + w * 3))
                l1_terrain[y, x] = 'flat'
    l2_type = nt

    # Stone edge exposure
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] == 'stone':
                has_open = any(0 <= y + dy < H and 0 <= x + dx < W
                               and l2_type[y + dy, x + dx] != 'stone'
                               and l1_terrain[y + dy, x + dx] not in ('water', 'trench')
                               for dy, dx in DIRS)
                if has_open and random.random() < 0.35:
                    l2_type[y, x] = ''
                    stone_amount[y, x] = 0

    # Phase 2: Vegetation
    veg_type = np.full((H, W), '', dtype=object)
    veg_yield = np.zeros((H, W), dtype=int)
    visited = np.zeros((H, W), dtype=bool)

    # Greytree forest patches (5-15 cells, ~60% fill)
    for y in range(H):
        w = abs(y - CENTER_Y) / CENTER_Y
        for x in range(W):
            if l2_type[y, x] != '' or l1_terrain[y, x] != 'flat' or visited[y, x]:
                continue
            m = moist[y, x]
            if random.random() < 0.04 * (1 - 0.5 * w) * (1 + m * 0.5):
                patch_size = random.randint(5, 15)
                q = deque([(y, x)]); cells = []; lv = {(y, x)}
                while q and len(cells) < patch_size:
                    cy, cx = q.popleft(); cells.append((cy, cx))
                    dirs_l = list(DIRS); random.shuffle(dirs_l)
                    for dy, dx in dirs_l:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and (ny, nx) not in lv:
                            lv.add((ny, nx))
                            if l2_type[ny, nx] == '' and l1_terrain[ny, nx] == 'flat' and not visited[ny, nx]:
                                q.append((ny, nx))
                for (cy, cx) in cells:
                    if random.random() < 0.60:
                        veg_type[cy, cx] = 'greytree'; veg_yield[cy, cx] = 2; visited[cy, cx] = True

    # Ashbush patches (1-4 cells)
    for y in range(H):
        w = abs(y - CENTER_Y) / CENTER_Y
        for x in range(W):
            if l2_type[y, x] != '' or l1_terrain[y, x] not in ('flat', 'sand') or visited[y, x]:
                continue
            m = moist[y, x]
            if random.random() < 0.10 * (1 - 0.3 * w) * (1 + m * 0.5):
                patch_size = random.randint(1, 4)
                q = deque([(y, x)]); cells = []; lv = {(y, x)}
                while q and len(cells) < patch_size:
                    cy, cx = q.popleft(); cells.append((cy, cx))
                    dirs_l = list(DIRS); random.shuffle(dirs_l)
                    for dy, dx in dirs_l:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and (ny, nx) not in lv:
                            lv.add((ny, nx))
                            if l2_type[ny, nx] == '' and l1_terrain[ny, nx] in ('flat', 'sand') and not visited[ny, nx]:
                                q.append((ny, nx))
                for (cy, cx) in cells:
                    veg_type[cy, cx] = 'ashbush'; veg_yield[cy, cx] = 1; visited[cy, cx] = True

    # Wallmoss: along Stone edges
    for y in range(H):
        for x in range(W):
            if l1_terrain[y, x] == 'flat' and l2_type[y, x] == '' and not visited[y, x]:
                has_stone = any(0 <= y + dy < H and 0 <= x + dx < W and l2_type[y + dy, x + dx] == 'stone'
                                for dy, dx in DIRS)
                if has_stone and random.random() < 0.08:
                    veg_type[y, x] = 'wallmoss'; veg_yield[y, x] = 1; visited[y, x] = True

    # Phase 3: Ore veins in Stone
    claimed = np.zeros((H, W), dtype=bool)
    stone_depth = np.full((H, W), -1, dtype=int)

    # Compute depth from nearest non-Stone cell
    q = deque()
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] != 'stone':
                stone_depth[y, x] = 0
                q.append((y, x, 0))
    while q:
        y, x, d = q.popleft()
        for dy, dx in DIRS:
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W and stone_depth[ny, nx] == -1:
                if l2_type[ny, nx] == 'stone':
                    stone_depth[ny, nx] = d + 1
                    q.append((ny, nx, d + 1))

    def _place_vein(ore_name: str, base_prob: float, min_sz: int, max_sz: int,
                    min_depth: int, lat_factor: float, _depth_factor: float):
        for y in range(H):
            w = abs(y - CENTER_Y) / CENTER_Y
            for x in range(W):
                if l2_type[y, x] != 'stone' or claimed[y, x]:
                    continue
                d = max(1, stone_depth[y, x])
                if d < min_depth: continue
                prob = base_prob * (1 + lat_factor * w)
                if random.random() >= prob: continue
                vein_sz = random.randint(min_sz, max_sz)
                vq = deque([(y, x)]); cells = []; vv = {(y, x)}
                while vq and len(cells) < vein_sz:
                    cy, cx = vq.popleft(); cells.append((cy, cx))
                    dirs_l = list(DIRS); random.shuffle(dirs_l)
                    for dy, dx in dirs_l:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < H and 0 <= nx < W and (ny, nx) not in vv:
                            vv.add((ny, nx))
                            if l2_type[ny, nx] == 'stone' and not claimed[ny, nx]:
                                vq.append((ny, nx))
                val = 3 if ore_name in ('gold', 'uranium') else 5
                for (cy, cx) in cells:
                    ore_type[cy, cx] = ore_name
                    ore_amount[cy, cx] = random.randint(1, 3) if ore_name in ('gold', 'uranium') else random.randint(2, val)
                    claimed[cy, cx] = True

    _place_vein('gold', 0.0008, 2, 5, 5, 5.0, 0)
    _place_vein('uranium', 0.003, 3, 8, 3, 3.0, 0)
    _place_vein('iron', 0.008, 4, 12, 1, 1.0, 5)
    _place_vein('copper', 0.012, 6, 20, 1, 0.3, 0)

    # Gold exclusivity
    for y in range(H):
        for x in range(W):
            if ore_type[y, x] == 'gold':
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < H and 0 <= nx < W and ore_type[ny, nx] in ('copper', 'iron', 'uranium'):
                            ore_type[ny, nx] = ''; ore_amount[ny, nx] = 0; claimed[ny, nx] = False

    # Ore exposure
    ore_exposed = np.zeros((H, W), dtype=bool)
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] == 'stone' and ore_type[y, x]:
                for dy, dx in DIRS:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W and l2_type[ny, nx] != 'stone':
                        ore_exposed[y, x] = True; break

    # Phase 4: Build tile list
    from .models import Tile, Terrain as T
    terrain_map = {'flat': T.FLAT, 'sand': T.SAND, 'rock': T.ROCK, 'water': T.WATER, 'trench': T.TRENCH}

    tiles = []
    for y in range(H):
        row = []
        for x in range(W):
            l1 = terrain_map.get(l1_terrain[y, x], T.FLAT)
            l2t = str(l2_type[y, x])
            tile = Tile(
                l1=l1, l2_type=l2t,
                stone_amount=int(stone_amount[y, x]),
                ore_type=str(ore_type[y, x]),
                ore_amount=int(ore_amount[y, x]),
                ore_exposed=bool(ore_exposed[y, x]),
                stone_depth=int(stone_depth[y, x]) if stone_depth[y, x] >= 0 else 0,
                veg_type=str(veg_type[y, x]),
                veg_yield=int(veg_yield[y, x]),
            )
            row.append(tile)
        tiles.append(row)

    return {
        "l1_terrain": l1_terrain,
        "l2_type": l2_type,
        "stone_amount": stone_amount,
        "ore_type": ore_type,
        "ore_amount": ore_amount,
        "ore_exposed": ore_exposed,
        "stone_depth": stone_depth,
        "veg_type": veg_type,
        "veg_yield": veg_yield,
        "tiles": tiles,
    }


def print_stats(result: dict):
    """Print terrain generation statistics."""
    l1_terrain = result["l1_terrain"]
    l2_type = result["l2_type"]
    stone_amount = result["stone_amount"]
    ore_type = result["ore_type"]
    ore_amount = result["ore_amount"]
    veg_type = result["veg_type"]
    exposed = result["ore_exposed"]

    T = W * H
    print("=== L1 Terrain ===")
    for t in ['flat', 'sand', 'rock', 'water', 'trench']:
        c = np.sum(l1_terrain == t); print(f'  {t:8s}: {c:6d} ({c/T*100:5.1f}%)')

    stone_cells = np.sum(l2_type == 'stone')
    print(f"\n=== L2 Stone (Stone cells={stone_cells}) ===")
    print(f'  Total stone={np.sum(stone_amount)}')

    print("\n=== Vegetation ===")
    for vt in ['ashbush', 'greytree', 'wallmoss']:
        c = np.sum(veg_type == vt); wd = np.sum(result["veg_yield"][veg_type == vt])
        print(f'  {vt:10s}: {c:5d} cells  wood={wd}')

    print("\n=== Ore Veins ===")
    for ot in ['copper', 'iron', 'uranium', 'gold']:
        c = np.sum(ore_type == ot); to = np.sum(ore_amount[ore_type == ot])
        print(f'  {ot:8s}: {c:4d} cells  ore={to:4d}')

    total_ore = np.sum(ore_type != '')
    exp_ore = np.sum(exposed)
    print(f"\n  Ore visible: exposed={exp_ore} ({exp_ore/max(1,total_ore)*100:.0f}%) hidden={total_ore-exp_ore}")
