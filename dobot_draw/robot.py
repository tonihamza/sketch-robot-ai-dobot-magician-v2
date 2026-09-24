"""Direct Magician Protocol2 serial transport. No vendor DLL or service.

Packet layouts checked against official DobotLink DMagicianProtocol.cpp.
No command is automatically retried: motion timeout is an ambiguous outcome.
"""
import math
import struct
import threading
import time
import serial


class RobotError(RuntimeError):
    pass


def packet(command, control=0, data=b''):
    payload = bytes((command, control)) + data
    return b'\xaa\xaa' + bytes((len(payload),)) + payload + bytes((-sum(payload) & 255,))


class Robot:
    def __init__(self, port):
        self.laser_session=False
        self.lock = threading.RLock()
        self.serial = serial.Serial()
        self.serial.port = port
        self.serial.baudrate = 115200
        self.serial.timeout = 0.05
        self.serial.write_timeout = 0.5
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.open()
        self.fault = False
        self.buffer = bytearray()
        try:
            self.serial.reset_input_buffer()
            self.identity = self.rpc(7).rstrip(b'\0').decode('ascii', errors='replace')
            if self.identity != 'Magician':
                raise RobotError(f'Dispozitiv neașteptat: {self.identity!r}')
            v = self.rpc(2)
            if len(v) < 3:
                raise RobotError('Versiune invalidă')
            self.version = '.'.join(map(str, v[:3]))
            self.pose()
        except Exception:
            self.serial.close()
            raise

    def rpc(self, command, control=0, data=b'', allow_fault=False):
        with self.lock:
            if self.fault and not allow_fault:
                raise RobotError('Legătură invalidată. Reconectează; nu se reia automat.')
            try:
                self.serial.write(packet(command, control, data))
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    self.buffer.extend(self.serial.read(max(1, self.serial.in_waiting)))
                    while len(self.buffer) >= 4:
                        start = self.buffer.find(b'\xaa\xaa')
                        if start < 0:
                            self.buffer[:] = self.buffer[-1:]
                            break
                        if start:
                            del self.buffer[:start]
                        if len(self.buffer) < 4:
                            break
                        length = self.buffer[2]
                        if length < 2:
                            del self.buffer[0]
                            continue
                        if len(self.buffer) < length + 4:
                            break
                        frame = bytes(self.buffer[3:length+4])
                        del self.buffer[:length+4]
                        if sum(frame) & 255:
                            raise RobotError('Checksum serial invalid')
                        if frame[0] == command and frame[1] & 1 == control & 1:
                            return frame[2:-1]
                raise RobotError(f'Timeout USB, comanda {command}. Nu se retransmite mișcarea.')
            except Exception:
                self.fault = True
                raise

    def pose(self):
        raw = self.rpc(10)
        if len(raw) != 32:
            raise RobotError('Răspuns GetPose invalid')
        values = struct.unpack('<8f', raw)
        if not all(math.isfinite(v) for v in values):
            raise RobotError('Coordonate invalide')
        return list(values)

    def alarms(self):
        raw = self.rpc(20)
        if len(raw) != 16:
            raise RobotError('Răspuns alarme invalid')
        return [i*8+b for i,v in enumerate(raw) for b in range(8) if v & (1 << b)]

    def check_clear(self):
        a = self.alarms()
        if a:
            raise RobotError(f'Alarme active: {a}. Nu sunt șterse automat.')

    def reachable(self, xyzr):
        result = self.rpc(15, 1, struct.pack('<B4f', 0, *xyzr))
        if len(result) != 1:
            raise RobotError('Controllerul nu confirmă verificarea accesibilității')
        return result[0] == 0

    def stop(self):
        # Send both even if acknowledgments are unavailable; no automatic lift.
        errors = []
        if getattr(self,'laser_session',False):
            try:self.laser_off()
            except Exception as e:errors.append(str(e))
        for cmd in (242, 245):
            try:
                self.rpc(cmd, 1, allow_fault=True)
            except Exception as e:
                errors.append(str(e))
        if getattr(self,'laser_session',False):
            try:self.laser_off()
            except Exception as e:errors.append(str(e))
        if errors:
            raise RobotError('STOP neconfirmat prin USB. ' + '; '.join(errors))

    def laser_off(self):
        # Immediate OFF also attempted after a transport fault; never retry ON.
        self.rpc(61,1,b'\x01\x00',allow_fault=True)

    def prepare_laser(self):
        self.laser_session=True
        self.laser_off()
        if self.rpc(61)!=b'\x01\x00':
            raise RobotError('Controllerul nu confirmă laserul oprit')

    def continuous_laser(self, points, power, cancel, progress=lambda n:None):
        if not math.isfinite(power) or not 0<power<=100:
            raise RobotError('Putere laser: peste 0 și maximum 100%')
        if not getattr(self,'laser_session',False):
            raise RobotError('Laserul nu a fost pregătit')
        try:
            self.continuous(points,cancel,progress,laser_power=power)
        finally:
            self.laser_off()

    def prepare(self, speed, z_speed=30):
        self.check_clear()
        self.stop()
        self.speed = speed
        self.rpc(81, 1, struct.pack('<4f', z_speed, 5, 100, 10))
        self.rpc(83, 1, struct.pack('<2f', 100, 100))
        read = self.rpc(81)
        if len(read) != 16 or abs(struct.unpack('<4f', read)[0] - z_speed) > max(.01, z_speed*1e-6):
            raise RobotError('Viteza nu a fost confirmată')
        ratios = self.rpc(83)
        if len(ratios) != 8 or struct.unpack('<2f', ratios) != (100, 100):
            raise RobotError('Raportul vitezei nu a fost confirmat')
        cp = struct.pack('<3fB', 100, speed, 100, 0)
        self.rpc(90, 1, cp)
        if self.rpc(90) != cp:
            raise RobotError('Parametrii mișcării continue CP nu au fost confirmați')
        self.rpc(240, 1)

    def continuous(self, points, cancel, progress=lambda n: None, *, laser_power=None):
        """Bounded lookahead: prefill stopped queue, then refill while it runs.

        CP has XYZ only; the last float is reserved, not a speed setting.
        WAIT creates an explicit end-of-stroke barrier before a pen lift.
        """
        from collections import deque
        pending = deque()
        sent = completed = 0
        total = len(points) + (2 if laser_power is not None else 1)
        running = False
        self.rpc(241, 1)
        stall_timeout = 15 + 2 / getattr(self, 'speed', 100)
        deadline = time.monotonic() + stall_timeout
        alarm_time = 0
        while completed < total:
            if cancel.is_set():
                raise RobotError('Oprit de utilizator')
            while sent < total and len(pending) < 16:
                if cancel.is_set():
                    raise RobotError('Oprit de utilizator')
                space = self.rpc(247)
                if len(space) not in (4, 8):
                    raise RobotError('Spațiul cozii CP nu a fost confirmat')
                if int.from_bytes(space, 'little') == 0:
                    break
                if sent < len(points):
                    raw = self.rpc(92 if laser_power is not None else 91, 3,
                                   struct.pack('<B4f', 1, *points[sent][:3], laser_power or 0))
                elif laser_power is not None and sent==len(points):
                    # OFF is executed in the same controller queue, before WAIT.
                    raw = self.rpc(61,3,b'\x01\x00')
                else:
                    raw = self.rpc(110, 3, struct.pack('<I', 1))
                if len(raw) != 8:
                    raise RobotError('Index de mișcare CP invalid')
                index = struct.unpack('<Q', raw)[0]
                if pending and index <= pending[-1]:
                    raise RobotError('Index de coadă CP neordonat')
                pending.append(index)
                sent += 1
            if not running:
                if not pending:
                    raise RobotError('Coada controllerului nu acceptă traseul CP')
                self.rpc(240, 1)
                running = True
            raw = self.rpc(246)
            if len(raw) != 8:
                raise RobotError('Index de execuție CP invalid')
            current = struct.unpack('<Q', raw)[0]
            advanced = False
            while pending and pending[0] <= current:
                pending.popleft();completed += 1;advanced = True
            if advanced:
                deadline = time.monotonic() + stall_timeout
                progress(min(completed, len(points)))
            if time.monotonic() >= alarm_time:
                self.check_clear()
                alarm_time = time.monotonic() + .2
            if time.monotonic() > deadline:
                raise RobotError('Mișcarea CP nu mai progresează')
            if cancel.wait(.01):
                raise RobotError('Oprit de utilizator')

    def move(self, xyzr, cancel, timeout=60):
        if cancel.is_set():
            raise RobotError('Oprit de utilizator')
        raw = self.rpc(84, 3, struct.pack('<B4f', 2, *xyzr))
        if len(raw) != 8:
            raise RobotError('Index de mișcare invalid')
        target = struct.unpack('<Q', raw)[0]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel.wait(.025):
                raise RobotError('Oprit de utilizator')
            current = self.rpc(246)
            if len(current) != 8:
                raise RobotError('Index de execuție invalid')
            if struct.unpack('<Q', current)[0] >= target:
                return
        raise RobotError('Mișcarea nu s-a terminat în timpul permis')

    def close(self):
        try:
            if getattr(self,'laser_session',False):self.stop()
        finally:self.serial.close()
