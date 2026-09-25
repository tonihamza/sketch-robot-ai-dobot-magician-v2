"""Local GB10 portrait client. Only the existing ComfyUI service uses the GPU."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent.parent
SERVER = 'http://127.0.0.1:8188'


def local_mode():
    backend = os.environ.get('DOBOT_AI_BACKEND', 'local' if sys.platform.startswith('linux') else 'ssh')
    if backend not in ('local', 'ssh'):
        raise ValueError('DOBOT_AI_BACKEND trebuie să fie local sau ssh')
    return backend == 'local'


def ready():
    try:
        with urllib.request.urlopen(SERVER+'/system_stats', timeout=2) as response:
            return isinstance(json.load(response).get('system'), dict)
    except (OSError, ValueError):
        return False


def ensure_service(cancel, status):
    if ready():
        return
    status('Pornesc serviciul AI local ComfyUI…')
    try:
        result = subprocess.run(['systemctl', '--user', 'start', 'hermes-comfyui.service'],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('Pornește ComfyUI local pe portul 8188, apoi reîncearcă.') from error
    if result.returncode:
        raise RuntimeError('Serviciul ComfyUI nu poate porni. Verifică hermes-comfyui.service.')
    deadline = time.monotonic()+120
    while time.monotonic() < deadline:
        if cancel.wait(1):
            raise RuntimeError('Generare anulată înainte de trimiterea fotografiei.')
        if ready():
            return
    raise RuntimeError('ComfyUI nu răspunde după pornire. Verifică jurnalul serviciului.')


def generate(photo, destination, cancel, status, steps=24, people=1):
    photo = Path(photo).resolve()
    if not isinstance(steps, int) or not 1 <= steps <= 100:
        raise ValueError('Numărul de pași AI trebuie să fie între 1 și 100')
    if type(people) is not int or people not in (1,2,3):
        raise ValueError('Alege 1, 2 sau 3 persoane')
    if not photo.is_file() or photo.stat().st_size > 30_000_000:
        raise ValueError('Alege o fotografie de maximum 30 MB')
    if cancel.is_set():
        raise RuntimeError('Generare anulată')
    ensure_service(cancel, status)
    if cancel.is_set():
        raise RuntimeError('Generare anulată')
    local = Path(destination).resolve()/('portrait-'+uuid.uuid4().hex)
    local.mkdir(parents=True)
    log = local/'generation.log'
    command = [sys.executable, '-u', str(ROOT/'generate_robot_portrait.py'),
               str(photo), str(local/'portrait'), '--server', SERVER,
               '--paper-mm', '80', '--steps', str(steps), '--people', str(people)]
    started = time.monotonic()
    status(f'AI local · Qwen · {steps} pași…')
    # File output avoids a blocked subprocess pipe and preserves diagnostic logs.
    with log.open('w', encoding='utf-8') as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   cwd=ROOT)
        try:
            next_status = started
            while process.poll() is None:
                if cancel.wait(.1) or time.monotonic()-started > 2100:
                    raise RuntimeError('Așteptare anulată. Jobul deja trimis la ComfyUI poate continua local.')
                if time.monotonic() >= next_status:
                    elapsed = int(time.monotonic()-started)
                    status(f'AI local · {steps} pași · {elapsed//60}:{elapsed%60:02d} minute')
                    next_status = time.monotonic()+5
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
    if cancel.is_set():
        raise RuntimeError('Preluare anulată')
    if process.returncode:
        raise RuntimeError(f'Generarea locală a eșuat. Detalii: {log}')
    result = local/'portrait.svg'
    if not result.is_file() or not result.stat().st_size:
        raise RuntimeError(f'Generarea nu a produs SVG-ul. Detalii: {log}')
    status(f'Portret local gata în {time.monotonic()-started:.0f} secunde')
    return result
