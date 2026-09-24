"""Install a desktop launcher for this checkout, without robot actions."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent.parent
def quoted(value):
    return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'

content = ('[Desktop Entry]\nType=Application\nName=Dobot Studio\n'
           'Comment=Portrete AI și desen SVG prin USB local\n'
           f'Exec=/usr/bin/env DOBOT_AI_BACKEND=local {quoted(root/".venv/bin/python")} {quoted(root/"start.py")}\n'
           'Icon=camera-photo\nTerminal=false\nCategories=Graphics;\nStartupNotify=true\n')
applications = Path.home()/'.local/share/applications'
applications.mkdir(parents=True, exist_ok=True)
launcher = applications/'dobot-studio.desktop'
launcher.write_text(content, encoding='utf-8')
launcher.chmod(0o755)
result = subprocess.run(['xdg-user-dir','DESKTOP'],capture_output=True,text=True)
desktop = Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else Path.home()/'Desktop'
desktop.mkdir(exist_ok=True)
copy = desktop/launcher.name
copy.write_text(content, encoding='utf-8'); copy.chmod(0o755)
subprocess.run(['gio','set',str(copy),'metadata::trusted','true'],check=False)
print(f'Launcher: {launcher}\nDesktop: {copy}')
