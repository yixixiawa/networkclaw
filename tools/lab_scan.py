"""统计每个实验的设备型号分布，区分「纯交换机」与「含路由器」。"""
import re
from pathlib import Path

DOC = Path('knowledge/experiments')
sw_only, with_router = [], []
for fp in sorted(DOC.glob('*.md')):
    m = re.match(r'^(\d+)-(.+)\.md$', fp.name)
    if not m:
        continue
    num, name = m.group(1), m.group(2)
    txt = fp.read_text(encoding='utf-8', errors='replace')
    models = re.findall(r'\|\s*([A-Z]+\d+)\s*\|\s*([A-Za-z0-9\-]+)\s*\|', txt)
    if not models:
        models = [(a, b) for a, b in re.findall(r'([A-Z]+\d+)\s*\|\s*([A-Za-z0-9\-]+)', txt)]
    mm = [b.upper() for _, b in models]
    if not mm:
        continue
    has_router = any(x.startswith(('AR', 'Router', 'NE', 'USG')) or x == 'ROUTER' for x in mm)
    (with_router if has_router else sw_only).append((num, name, sorted(set(mm))))

print(f'纯交换机实验 {len(sw_only)} 个：')
for n, nm, mm in sw_only:
    print(f'  {n}  {nm[:34]:36} {",".join(mm)[:40]}')
print(f'\n含路由器实验 {len(with_router)} 个：')
for n, nm, mm in with_router[:12]:
    print(f'  {n}  {nm[:34]:36} {",".join(mm)[:40]}')
print('  ...' if len(with_router) > 12 else '')
print('\n纯交换机编号（可直接跑）:', ','.join(n for n, _, _ in sw_only))
