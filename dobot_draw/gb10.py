"""Photo transfer and portrait generation over authenticated SSH, without motion."""
import shlex
import time
import uuid
from pathlib import Path

import paramiko

HOST = '100.111.144.112'
USER = 'toni'
PROJECT = '/home/toni/dobot-studio'
PYTHON = '/home/toni/ComfyUI/.venv/bin/python'


def generate(photo, destination, password, cancel, status, host=HOST, user=USER, steps=24):
    if not isinstance(steps, int) or not 1 <= steps <= 100:
        raise ValueError('Numărul de pași AI trebuie să fie între 1 și 100')
    photo = Path(photo)
    if not photo.is_file() or photo.stat().st_size > 30_000_000:
        raise ValueError('Alege o fotografie de maximum 30 MB')
    client = paramiko.SSHClient()
    # The host was enrolled through OpenSSH during setup. Never silently trust
    # a different host key and never persist the password.
    client.load_system_host_keys(str(Path.home()/'.ssh'/'known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    job = 'portrait-' + uuid.uuid4().hex
    remote = PROJECT + '/jobs/' + job
    local = Path(destination)/job
    try:
        status('Conectare la GB10…')
        client.connect(host, username=user, password=password, timeout=15,
                       auth_timeout=15, banner_timeout=15,
                       look_for_keys=False, allow_agent=False)
        client.get_transport().set_keepalive(20)
        with client.open_sftp() as sftp:
            try:
                sftp.stat(PROJECT+'/jobs')
            except FileNotFoundError:
                sftp.mkdir(PROJECT+'/jobs')
            sftp.mkdir(remote)
            source = remote+'/source'+photo.suffix.lower()
            def transferred(sent, total):
                if cancel.is_set():
                    raise RuntimeError('Transfer anulat')
            status('Trimit fotografia originală pe GB10…')
            sftp.put(str(photo), source, callback=transferred)
            command = shlex.join([PYTHON, '-u', PROJECT+'/generate_robot_portrait.py',
                                  source, remote+'/portrait', '--paper-mm', '80', '--steps', str(steps)])
            # A dedicated PTY permits Ctrl-C to cancel this client only.
            _, stdout, _ = client.exec_command(command, get_pty=True)
            channel = stdout.channel
            deadline = time.monotonic()+2100
            started = time.monotonic()
            next_status = started+5
            tail = ''
            status(f'GB10 generează portretul cu Qwen · {steps} pași…')
            while True:
                while channel.recv_ready():
                    tail = (tail+channel.recv(8192).decode('utf-8', errors='replace'))[-12000:]
                if channel.exit_status_ready() and not channel.recv_ready():
                    break
                if cancel.is_set() or time.monotonic()>deadline:
                    channel.send('\x03')
                    raise RuntimeError('Așteptare anulată. Generarea deja trimisă la ComfyUI poate continua pe GB10.')
                if time.monotonic()>=next_status:
                    elapsed=int(time.monotonic()-started)
                    stage='Conversie SVG' if 'AI elapsed:' in tail else f'Generare Qwen · {steps} pași'
                    status(f'GB10 · {stage} · {elapsed//60}:{elapsed%60:02d} minute')
                    next_status=time.monotonic()+5
                cancel.wait(.1)
            code = channel.recv_exit_status()
            if code:
                local.mkdir(parents=True, exist_ok=True)
                (local/'generation.log').write_text(tail, encoding='utf-8')
                if 'Connection refused' in tail and '8188' in tail:
                    raise RuntimeError('ComfyUI nu răspunde pe GB10 (portul 8188). '
                                       'Serviciul AI este oprit sau încă pornește. '
                                       'Reîncearcă după pornirea serviciului.\n'
                                       f'Detalii salvate în: {local / "generation.log"}')
                raise RuntimeError('Generarea pe GB10 a eșuat:\n'+tail[-2500:])
            if cancel.is_set():
                raise RuntimeError('Preluare anulată')
            status('Descarc SVG-ul și previzualizarea…')
            local.mkdir(parents=True, exist_ok=False)
            for name in ('portrait.svg', 'portrait.png', 'portrait_ai_raw.png'):
                if sftp.stat(remote+'/'+name).st_size > 30_000_000:
                    raise RuntimeError('Rezultat GB10 prea mare')
                sftp.get(remote+'/'+name, str(local/name))
            (local/'generation.log').write_text(tail, encoding='utf-8')
            return local/'portrait.svg'
    finally:
        client.close()
