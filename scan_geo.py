import os, re, json
from collections import defaultdict

proj_geo = defaultdict(list)
proj_folder_map = {}

for root, dirs, files in os.walk('downloads'):
    for f in files:
        if f.lower().endswith(('.kml', '.kmz', '.geojson', '.shp', '.gpkg')):
            rel = os.path.relpath(root, 'downloads')
            proj_folder = rel.split(os.sep)[0]
            m = re.match(r'VCS_(\d+)_', proj_folder)
            proj_id = int(m.group(1)) if m else proj_folder
            proj_folder_map[proj_id] = proj_folder
            proj_geo[proj_id].append({'file': f, 'path': os.path.join(root, f)})

multi = {pid: fs for pid, fs in proj_geo.items() if len(fs) > 1}
print(f'Projetos com MULTIPLOS arquivos geo: {len(multi)}')
for pid, fs in list(multi.items())[:10]:
    names = [f['file'] for f in fs]
    print(f'  VCS_{pid}: {names}')

print(f'\nTotal projetos com 1 arquivo geo: {len(proj_geo) - len(multi)}')
print(f'Total projetos com geo: {len(proj_geo)}')

# Salvar mapa completo em JSON para uso posterior
geo_index = {}
for pid, fs in proj_geo.items():
    geo_index[str(pid)] = {
        'folder': proj_folder_map.get(pid, ''),
        'files': [f['path'] for f in fs]
    }
with open('verra_geo_index.json', 'w', encoding='utf-8') as fh:
    json.dump(geo_index, fh, ensure_ascii=False, indent=2)
print('\n[OK] verra_geo_index.json salvo')
