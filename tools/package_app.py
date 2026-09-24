"""Build source + Windows/Python 3.12 offline wheels, excluding local robot data."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root=Path(__file__).resolve().parent.parent
destination=root/'dist'/'Dobot-SVG-USB.zip'
destination.parent.mkdir(exist_ok=True)
files=[root/name for name in ('start.py','generate_robot_portrait.py','qwen_lineart_workflow_api.json','requirements.txt','Porneste.bat','Instaleaza.bat','README.md','GB10.md','LICENSE','THIRD_PARTY.md','install-gb10.sh','start-gb10.sh','tools/install_desktop.py')]
for name in ('dobot_draw','examples','tests','wheels','linux'):
    files.extend(p for p in (root/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
with ZipFile(destination,'w',ZIP_DEFLATED) as archive:
    for p in files:archive.write(p,Path('Dobot-SVG-USB')/p.relative_to(root))
print(destination)
print(f'{destination.stat().st_size/1_000_000:.1f} MB; {len(files)} files')
