# Biblioteci și surse

- pyserial 3.5 — BSD-3-Clause: https://github.com/pyserial/pyserial/blob/master/LICENSE.txt
- svgelements 1.9.6 — MIT: https://github.com/meerk40t/svgelements/blob/master/LICENSE
- NumPy 2.2.6 — BSD-3-Clause și notificările bibliotecilor incluse în distribuția wheel: https://github.com/numpy/numpy/blob/v2.2.6/LICENSE.txt
- Python/Tk nu sunt redistribuite în arhiva sursă. Instalarea locală folosește runtime-ul Python existent.

Fișierele wheel păstrează licențele pachetelor. Codul nou folosește importuri ale bibliotecilor; nu încorporează sursa DobotLink și nu redistribuie firmware sau DLL-uri Dobot.

Protocolul a fost verificat prin sursa oficială DobotLink (README declară LGPL), commit 80c6ad78010721648ad671cc47320604d303f1d9:
https://github.com/Dobot-Arm/DobotLink

Documentație oficială pentru Magician:
- Geometrie 135/147 mm, capitolul 3: https://download.dobot.cc/product-manual/dobot-magician/pdf/V1.7.0/en/Dobot-Magician-User-Guide-V1.7.0.pdf
- Intervalele recomandate pentru articulații, capitolul Teaching & Playback, și procedura Unlock: https://download.dobot.cc/product-manual/dobot-magician/v2/en/Dobot-Magician-V2-User-Guide-V1.9.0.pdf
- Alarme și codificarea pe biți: https://download.dobot.cc/product-manual/dobot-magician/pdf/en/Dobot-Magician-ALARM-Description.pdf

O copie de cercetare DobotLink poate exista local în research/, exclusă din arhiva aplicației și din Git. Nu este necesară la rulare.

- Paramiko 4.0.0 — LGPL-2.1: https://github.com/paramiko/paramiko/blob/4.0.0/LICENSE
- Dependențele SSH bcrypt, cryptography, invoke, PyNaCl, cffi și pycparser sunt distribuite în wheels cu propriile licențe și notificări incluse.

- Pillow 11.3.0 — HPND (licența inclusă în wheel).
- OpenCV Python headless 4.12.0.88 — OpenCV Apache-2.0 și notificările componentelor incluse în wheel. Folosit doar pentru captură video; interfața rămâne Tk.
- Requests 2.32.5 — Apache-2.0, pentru API-ul ComfyUI local; dependențele păstrează propriile licențe.
