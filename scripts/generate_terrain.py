#!/usr/bin/env python3
"""Ember Protocol — 地形生成器 v3.1
L1基岩(永久地板) + L2 Stone(可开采石料矿层) + 矿脉(种子+BFS) + 植被(斑块)
"""

import numpy as np
from PIL import Image, ImageDraw
from collections import deque, Counter
import random

random.seed(42)
np.random.seed(42)

W, H = 200, 200
CENTER_Y = 99.5
DIRS = [(0,1),(0,-1),(1,0),(-1,0)]
H1, H2 = 374761393, 668265263

def fbm(scale, octaves=3, seed=0):
    rng = np.random.RandomState(seed)
    result = np.zeros((H, W), dtype=np.float32)
    amp, total = 1.0, 0.0
    for _ in range(octaves):
        gw, gh = max(2, int(W * scale)), max(2, int(H * scale))
        coarse = rng.rand(gh, gw).astype(np.float32)
        img = Image.fromarray((coarse * 255).astype(np.uint8))
        layer = np.array(img.resize((W, H), Image.BILINEAR), dtype=np.float32) / 255.0
        result += layer * amp; total += amp; amp *= 0.5; scale *= 2.0
    return result / total

# ============================================================
# Phase 1: L1 基岩地形 + L2 Stone 矿层
# ============================================================
def generate_terrain():
    """
    L1: flat, sand, rock(基岩), water, trench — 全部永久不可开采
    L2: stone(石料矿层) — 铺在L1之上, amount次可开采, 含矿脉
    """
    rock_field = fbm(0.04, octaves=3, seed=42)
    detail = fbm(0.18, octaves=2, seed=99)
    moist = fbm(0.05, octaves=2, seed=77)

    # L1 永久地形
    l1_terrain = np.full((H, W), '', dtype=object)
    # L2 覆盖物: 'stone' | '' | 'veg'...
    l2_type = np.full((H, W), '', dtype=object)
    # L2 Stone: amount(开采次数), ore_type, ore_amount
    stone_amount = np.zeros((H, W), dtype=int)
    ore_type = np.full((H, W), '', dtype=object)
    ore_amount = np.zeros((H, W), dtype=int)

    for y in range(H):
        w = abs(y - CENTER_Y) / CENTER_Y
        for x in range(W):
            # L1 判定
            threshold = 0.70 - w * 0.35 + (detail[y, x] - 0.5) * 0.06

            if rock_field[y, x] > threshold:
                # L2 Stone 覆盖在此格: L1 混合 flat/rock 基岩
                l1_terrain[y, x] = 'rock' if random.random() < 0.35 else 'flat'
                l2_type[y, x] = 'stone'
                stone_amount[y, x] = max(3, min(12, int(5 + w * 4 + (rock_field[y,x]-threshold)*10)))
            else:
                m = moist[y, x]
                if m > 0.74 and w > 0.12 and rock_field[y, x] < 0.25:
                    l1_terrain[y, x] = 'water' if m > 0.80 else 'trench'
                elif m > 0.50:
                    l1_terrain[y, x] = 'sand'
                else:
                    l1_terrain[y, x] = 'flat'
                l2_type[y, x] = ''  # 无L2覆盖
                stone_amount[y, x] = 0

    # 薄Stone区域直接暴露L1 (模拟自然侵蚀/浅矿层)
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] == 'stone' and stone_amount[y, x] <= 4:
                l2_type[y, x] = ''
                stone_amount[y, x] = 0
                # L1保持原样 (flat或rock, 由上面随机决定)

    # 1轮清理: 移除完全孤立Stone, 填充被Stone包围单格
    nt = l2_type.copy()
    for y in range(H):
        for x in range(W):
            nb = sum(1 for dy, dx in DIRS
                     if 0 <= y+dy < H and 0 <= x+dx < W
                     and l2_type[y+dy, x+dx] == 'stone')
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

    # Stone边缘随机L1露头 (形成天然矿洞入口, 增大到35%)
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] == 'stone':
                has_open = any(0 <= y+dy < H and 0 <= x+dx < W
                               and l2_type[y+dy, x+dx] != 'stone'
                               and l1_terrain[y+dy, x+dx] not in ('water', 'trench')
                               for dy, dx in DIRS)
                if has_open and random.random() < 0.35:
                    l2_type[y, x] = ''
                    stone_amount[y, x] = 0
                    # L1保持原样（可能是flat或rock）

    return l1_terrain, l2_type, stone_amount, ore_type, ore_amount

# ============================================================
# Phase 2: L2 植被 (种子+BFS斑块)
# ============================================================
def generate_vegetation(l1_terrain, l2_type, moist):
    veg_type = np.full((H, W), '', dtype=object)
    veg_yield = np.zeros((H, W), dtype=int)
    visited = np.zeros((H, W), dtype=bool)

    # 灰木树森林斑块 (5~15格, ~60%填充)
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
                    dirs_l = [(0,1),(0,-1),(1,0),(-1,0)]; random.shuffle(dirs_l)
                    for dy, dx in dirs_l:
                        ny, nx = cy+dy, cx+dx
                        if 0<=ny<H and 0<=nx<W and (ny,nx) not in lv:
                            lv.add((ny,nx))
                            if l2_type[ny,nx]=='' and l1_terrain[ny,nx]=='flat' and not visited[ny,nx]:
                                q.append((ny,nx))
                for (cy, cx) in cells:
                    if random.random() < 0.60:
                        veg_type[cy, cx] = 'greytree'; veg_yield[cy, cx] = 2; visited[cy, cx] = True

    # 余烬灌木小斑块 (1~4格)
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
                    dirs_l = [(0,1),(0,-1),(1,0),(-1,0)]; random.shuffle(dirs_l)
                    for dy, dx in dirs_l:
                        ny, nx = cy+dy, cx+dx
                        if 0<=ny<H and 0<=nx<W and (ny,nx) not in lv:
                            lv.add((ny,nx))
                            if l2_type[ny,nx]=='' and l1_terrain[ny,nx] in ('flat','sand') and not visited[ny,nx]:
                                q.append((ny,nx))
                for (cy, cx) in cells:
                    veg_type[cy, cx] = 'ashbush'; veg_yield[cy, cx] = 1; visited[cy, cx] = True

    # 壁生苔: 沿Stone边缘单格
    for y in range(H):
        for x in range(W):
            if l1_terrain[y, x] == 'flat' and l2_type[y, x] == '' and not visited[y, x]:
                has_stone = any(0<=y+dy<H and 0<=x+dx<W and l2_type[y+dy,x+dx]=='stone'
                                for dy, dx in DIRS)
                if has_stone and random.random() < 0.08:
                    veg_type[y, x] = 'wallmoss'; veg_yield[y, x] = 1; visited[y, x] = True

    return veg_type, veg_yield

# ============================================================
# Phase 3: Stone 内矿脉 (种子+BFS, 按稀有度)
# ============================================================
def generate_ores(l1_terrain, l2_type, stone_amount):
    ore_type = np.full((H, W), '', dtype=object)
    ore_amount = np.zeros((H, W), dtype=int)
    exposed = np.zeros((H, W), dtype=bool)
    claimed = np.zeros((H, W), dtype=bool)

    # 深度: 距最近非Stone格的曼哈顿距离 (Stone内部深度)
    depth = np.full((H, W), -1, dtype=int)
    q = deque()
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] != 'stone':
                depth[y, x] = 0
                q.append((y, x, 0))
    while q:
        y, x, d = q.popleft()
        for dy, dx in DIRS:
            ny, nx = y+dy, x+dx
            if 0<=ny<H and 0<=nx<W and depth[ny,nx]==-1:
                if l2_type[ny, nx] == 'stone':
                    depth[ny, nx] = d+1
                    q.append((ny, nx, d+1))

    def try_place_vein(ore_name, seed_prob, min_sz, max_sz, min_depth, lat_factor, depth_factor):
        for y in range(H):
            w = abs(y - CENTER_Y) / CENTER_Y
            for x in range(W):
                if l2_type[y, x] != 'stone' or claimed[y, x]:
                    continue
                d = max(1, depth[y, x])
                if d < min_depth: continue
                prob = seed_prob * (1 + lat_factor * w)
                if depth_factor > 0: prob *= min(1.0, d / depth_factor)
                if random.random() >= prob: continue

                vein_sz = random.randint(min_sz, max_sz)
                vq = deque([(y, x)]); cells = []; vv = {(y, x)}
                while vq and len(cells) < vein_sz:
                    cy, cx = vq.popleft(); cells.append((cy, cx))
                    dirs_l = [(0,1),(0,-1),(1,0),(-1,0)]; random.shuffle(dirs_l)
                    for dy, dx in dirs_l:
                        ny, nx = cy+dy, cx+dx
                        if 0<=ny<H and 0<=nx<W and (ny,nx) not in vv:
                            vv.add((ny,nx))
                            if l2_type[ny,nx]=='stone' and not claimed[ny,nx]:
                                vq.append((ny,nx))
                val = 3 if ore_name in ('gold','uranium') else 5
                for (cy, cx) in cells:
                    ore_type[cy, cx] = ore_name
                    ore_amount[cy, cx] = random.randint(1, 3) if ore_name in ('gold','uranium') else random.randint(2, 5)
                    claimed[cy, cx] = True

    try_place_vein('gold',    0.0008, 2,  5,  5, 5.0, 0)
    try_place_vein('uranium', 0.003,  3,  8,  3, 3.0, 0)
    try_place_vein('iron',    0.008,  4, 12,  1, 1.0, 5)
    try_place_vein('copper',  0.012,  6, 20,  1, 0.3, 0)

    # 金矿排他
    for y in range(H):
        for x in range(W):
            if ore_type[y, x] == 'gold':
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        ny, nx = y+dy, x+dx
                        if 0<=ny<H and 0<=nx<W and ore_type[ny,nx] in ('copper','iron','uranium'):
                            ore_type[ny,nx] = ''; ore_amount[ny,nx] = 0; claimed[ny,nx] = False

    # 暴露性
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] == 'stone' and ore_type[y, x]:
                for dy, dx in DIRS:
                    ny, nx = y+dy, x+dx
                    if 0<=ny<H and 0<=nx<W and l2_type[ny, nx] != 'stone':
                        exposed[y, x] = True; break

    return ore_type, ore_amount, exposed, depth

# ============================================================
# Phase 4: 渲染
# ============================================================
def render(l1_terrain, l2_type, stone_amount, veg_type, ore_type, ore_amount, exposed, depth, fn, scale=4):
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb_oremap = np.zeros((H, W, 3), dtype=np.uint8)

    TC = {
        'flat': np.array([70, 135, 48]),
        'sand': np.array([194, 178, 128]),
        'rock': np.array([110, 100, 85]),    # L1基岩地板: 棕灰色, 与Stone灰阶区分
        'water': np.array([25, 100, 210]),
        'trench': np.array([55, 42, 30]),
    }
    OC = {
        'copper': np.array([210, 125, 45]),
        'iron': np.array([135, 115, 95]),
        'uranium': np.array([75, 200, 55]),
        'gold': np.array([255, 215, 40]),
    }
    VC = {
        'ashbush': np.array([120, 100, 40]),
        'greytree': np.array([55, 65, 45]),
        'wallmoss': np.array([90, 130, 70]),
    }

    # L1 基色
    for y in range(H):
        for x in range(W):
            t = l1_terrain[y, x]
            if t in TC:
                bv = TC[t].astype(float) + (x*H1 + y*H2) % 10 - 5
                rgb[y, x] = bv.clip(0, 255).astype(np.uint8)

    # L2 Stone 叠加
    for y in range(H):
        for x in range(W):
            if l2_type[y, x] == 'stone':
                amt = stone_amount[y, x]
                d = max(1, min(10, depth[y, x]))
                base = 160 - d * 7 + amt * 1.5
                r = int(base + (x*H1+y*H2)%7 - 3 + (10-d)*2)
                g = int(base + (x*H2+y*H1)%7 - 3)
                b = int(base + (x*H1+y*H2)%6 - 3 - 2)
                rgb[y, x] = [max(50, min(200, r)), max(50, min(200, g)), max(50, min(200, b))]

    rgb_oremap = rgb.copy()

    # L2 植被
    for y in range(H):
        for x in range(W):
            vt = veg_type[y, x]; vc = VC.get(vt)
            if vc is not None:
                base = rgb[y, x].astype(float)
                blended = (base * 0.35 + vc.astype(float) * 0.65).astype(np.uint8)
                rgb[y, x] = blended; rgb_oremap[y, x] = blended

    # 矿脉 (游戏视图=仅裸露, 矿脉全览=全部可见)
    for y in range(H):
        for x in range(W):
            ot = ore_type[y, x]
            if ot and ore_amount[y, x] > 0:
                base = rgb[y, x].astype(float); oc_arr = OC[ot].astype(float)
                bl_game = 0.55 if exposed[y, x] else 0.08
                rgb[y, x] = (base * (1 - bl_game) + oc_arr * bl_game).astype(np.uint8)
                rgb_oremap[y, x] = (base * 0.55 + oc_arr * 0.45).astype(np.uint8)

    # --- 游戏视图 ---
    img = Image.fromarray(rgb, 'RGB').resize((W * scale, H * scale), Image.NEAREST)
    d = ImageDraw.Draw(img); ly = 6
    legend = [
        ('L1 平地 flat', (70,135,48)), ('L1 沙地 sand', (194,178,128)),
        ('L1 基岩 rock(地板)', (110,100,85)),
        ('L2 Stone(可采石料)', (130,130,125)), ('水域 water', (25,100,210)),
        ('沟壑 trench', (55,42,30)), ('灌木', (120,100,40)),
        ('树', (55,65,45)), ('铜Cu', (210,125,45)),
        ('铁Fe', (135,115,95)), ('铀U', (75,200,55)), ('金Au', (255,215,40)),
    ]
    for lb, cl in legend:
        d.rectangle([8, ly, 24, ly+16], fill=cl, outline=(180,180,180))
        d.text((30, ly), lb, fill=(220,220,220)); ly += 18
    d.text((8, ly+2), 'L1=永久基岩(不可开采) | L2 Stone=可开采石料(深度=颜色深浅) | 裸露矿=Stone边缘可见', fill=(150,150,150))
    img.save(fn)

    # --- 矿脉全览 ---
    orefn = fn.replace('.png', '_ores.png')
    img2 = Image.fromarray(rgb_oremap, 'RGB').resize((W * scale, H * scale), Image.NEAREST)
    d2 = ImageDraw.Draw(img2); ly = 6
    for lb, cl in legend:
        d2.rectangle([8, ly, 24, ly+16], fill=cl, outline=(180,180,180))
        d2.text((30, ly), lb, fill=(220,220,220)); ly += 18
    d2.text((8, ly+2), '【矿脉全览】所有矿脉可见 (Agent视角仅裸露矿石可见)', fill=(255,180,50))
    img2.save(orefn)
    print(f'已保存: {fn}  (游戏视图)')
    print(f'已保存: {orefn}  (矿脉全览)')
    return img, img2

# ============================================================
# Phase 5: 统计
# ============================================================
def full_stats(l1_terrain, l2_type, stone_amount, veg_type, ore_type, ore_amount, exposed, depth):
    T = W * H
    print("=== L1 基岩地形 ===")
    for t in ['flat', 'sand', 'rock', 'water', 'trench']:
        c = np.sum(l1_terrain == t); print(f'  {t:8s}: {c:6d} ({c/T*100:5.1f}%)')

    stone_cells = np.sum(l2_type == 'stone')
    print(f"\n=== L2 Stone 矿层 (Stone格={stone_cells}) ===")
    print(f'  总石料={np.sum(stone_amount)} 人均={np.sum(stone_amount)/20:.0f} 均/格={np.sum(stone_amount)/stone_cells:.1f}' if stone_cells>0 else '')

    print("\n=== L2 植被 ===")
    for vt in ['ashbush', 'greytree', 'wallmoss']:
        c = np.sum(veg_type == vt); wd = np.sum(veg_yield[veg_type == vt])
        vis = np.zeros((H,W),bool); patches = []
        for y in range(H):
            for x in range(W):
                if veg_type[y,x]==vt and not vis[y,x]:
                    vq=deque([(y,x)]); vis[y,x]=True; sz=0
                    while vq:
                        cy,cx=vq.popleft(); sz+=1
                        for dy,dx in DIRS:
                            ny,nx=cy+dy,cx+dx
                            if 0<=ny<H and 0<=nx<W and veg_type[ny,nx]==vt and not vis[ny,nx]:
                                vis[ny,nx]=True; vq.append((ny,nx))
                    patches.append(sz)
        avg_p = sum(patches)/len(patches) if patches else 0
        print(f'  {vt:10s}: {c:5d}格 {len(patches):4d}片 均{avg_p:.0f}格/片 木质={wd}')

    print(f"\n=== Stone内矿脉 ===")
    for ot in ['copper', 'iron', 'uranium', 'gold']:
        c = np.sum(ore_type == ot); to = np.sum(ore_amount[ore_type == ot])
        vis = np.zeros((H,W),bool); veins = []
        for y in range(H):
            for x in range(W):
                if ore_type[y,x]==ot and not vis[y,x]:
                    vq=deque([(y,x)]); vis[y,x]=True; sz=0
                    while vq:
                        cy,cx=vq.popleft(); sz+=1
                        for dy,dx in DIRS:
                            ny,nx=cy+dy,cx+dx
                            if 0<=ny<H and 0<=nx<W and ore_type[ny,nx]==ot and not vis[ny,nx]:
                                vis[ny,nx]=True; vq.append((ny,nx))
                    veins.append(sz)
        avg_v = sum(veins)/len(veins) if veins else 0
        print(f'  {ot:8s}: {c:4d}格 {len(veins):3d}条脉 均{avg_v:.0f}格/脉 矿量={to:4d} 人均={to/20:5.0f}')

    print("\n=== 纬度渐变 ===")
    for ys in range(0, 200, 20):
        ye = ys+20; b = l2_type[ys:ye, :]; Tb = b.size
        sc = np.sum(b == 'stone'); nc = np.sum((b != 'stone') & (l1_terrain[ys:ye,:] != 'water') & (l1_terrain[ys:ye,:] != 'trench'))
        w = abs((ys+10)-CENTER_Y)/CENTER_Y
        print(f'  Y{ys:3d}-{ye-1:3d}: Stone{sc/Tb*100:5.0f}% 空地{nc/Tb*100:5.0f}% rad{w*30:4.0f}%')

    dc = Counter()
    for y in range(H):
        for x in range(W):
            if l2_type[y,x] == 'stone': dc[min(10, depth[y,x])] += 1
    print(f"\n=== Stone深度 ===")
    for d in sorted(dc.keys()):
        print(f'  d={d:2d}: {dc[d]:5d} ({dc[d]/stone_cells*100:5.1f}%)')

    total_ore = np.sum(ore_type != '')
    exp_ore = sum(1 for y in range(H) for x in range(W) if ore_type[y,x]!='' and exposed[y,x])
    print(f"\n  矿石可见: 裸露{exp_ore}({exp_ore/total_ore*100:.0f}%) 隐藏{total_ore-exp_ore}({(total_ore-exp_ore)/total_ore*100:.0f}%)")

# ============================================================
if __name__ == '__main__':
    print("=== Phase 1: L1基岩 + L2 Stone ===")
    l1_terrain, l2_type, stone_amount, ore_type, ore_amount = generate_terrain()

    print("=== Phase 2: L2 植被 ===")
    moist = fbm(0.05, octaves=2, seed=77)
    veg_type, veg_yield = generate_vegetation(l1_terrain, l2_type, moist)

    print("=== Phase 3: Stone内矿脉 ===")
    ore_type2, ore_amount2, exposed, depth = generate_ores(l1_terrain, l2_type, stone_amount)
    # 合并矿脉数据 (generate_terrain只占位, generate_ores实际生成)
    ore_type = ore_type2
    ore_amount = ore_amount2

    print("=== Phase 4: 统计 ===")
    full_stats(l1_terrain, l2_type, stone_amount, veg_type, ore_type, ore_amount, exposed, depth)

    print("\n=== Phase 5: 渲染 ===")
    render(l1_terrain, l2_type, stone_amount, veg_type, ore_type, ore_amount, exposed, depth,
           '/Users/yz/Desktop/Ember-protocol/output/terrain_v1.2.0.png')
