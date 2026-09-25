import math
import numpy as np


class Calibration:
    """Rectangular XY frame with constant contact Z = highest measured corner.

    Raw measurements remain untouched for independent kinematic validation.
    The spring pen can compress differently at each manual corner capture.
    """
    def __init__(self, corners):
        p = np.asarray(corners, dtype=float)
        if p.shape != (4, 3) or not np.isfinite(p).all():
            raise ValueError('Sunt necesare patru puncte XYZ finite')
        self.corners = p.tolist()
        self.contact_z = float(np.max(p[:,2]))
        self.z_spread = float(np.ptp(p[:,2]))
        p = p.copy()
        p[:,2] = self.contact_z
        self.center = p.mean(axis=0)
        u = (p[1]-p[0]+p[2]-p[3])/2
        v = (p[3]-p[0]+p[2]-p[1])/2
        self.width, self.height = float(np.linalg.norm(u)), float(np.linalg.norm(v))
        if not (70 <= self.width <= 90 and 70 <= self.height <= 90):
            raise ValueError(f'Colțurile măsoară {self.width:.1f} × {self.height:.1f} mm; așteptat circa 80 × 80 mm')
        self.u = u / self.width
        v -= self.u * np.dot(v, self.u)
        self.v = v / np.linalg.norm(v)
        self.normal = np.cross(self.u, self.v)
        expected = np.array([self.world(x,y) for x,y in ((0,0),(self.width,0),(self.width,self.height),(0,self.height))])
        self.residual = float(np.max(np.linalg.norm(p-expected, axis=1)))
        if self.residual > 1.5:
            raise ValueError(f'Colțurile XY nu formează un dreptunghi (abatere {self.residual:.2f} mm). Recalibrează.')

    def world(self, x, y, offset=0):
        p = self.center + (x-self.width/2)*self.u + (y-self.height/2)*self.v
        return p + np.array([0,0,offset])

    def local(self, xyz):
        # XY inverse keeps a vertical pen lift at the same paper location.
        xy = np.asarray(xyz)[:2] - self.center[:2]
        a,b = np.linalg.solve(np.column_stack((self.u[:2],self.v[:2])),xy)
        x,y = a+self.width/2,b+self.height/2
        dz = float(xyz[2] - self.world(x,y)[2])
        return float(x),float(y),dz

    def inside(self, xyz, inset=2):
        x,y,_ = self.local(xyz)
        return inset <= x <= self.width-inset and inset <= y <= self.height-inset


def optimize(paths):
    remaining = [list(p) for p in paths]
    result = []
    pos = (0,0)
    while remaining:
        _, i, reverse = min((math.dist(pos,p[-1] if reverse else p[0]),i,reverse)
                            for i,p in enumerate(remaining) for reverse in (False,True))
        p = remaining.pop(i)
        if reverse:
            p.reverse()
        result.append(p)
        pos = p[-1]
    # Reverse a sequence AND each stroke: internal pen-up distances and all
    # drawn segments stay identical; only its two boundary travels change.
    # Bounded lookahead keeps preview responsive for complex SVGs.
    for _ in range(3):
        changed = False
        for i in range(len(result)):
            before = result[i-1][-1] if i else (0,0)
            for j in range(i, min(len(result), i+64)):
                after = result[j+1][0] if j+1 < len(result) else None
                old = math.dist(before, result[i][0])
                new = math.dist(before, result[j][-1])
                if after is not None:
                    old += math.dist(result[j][-1], after)
                    new += math.dist(result[i][0], after)
                if new < old - 1e-6:
                    result[i:j+1] = [list(reversed(p)) for p in reversed(result[i:j+1])]
                    changed = True
        if not changed:
            break
    return result


def join_nearby(paths, gap=.3):
    """Join open endpoints only when their tangents continue the same line.

    A join draws a straight bridge. Never join closed outlines or parallel
    strokes sideways. Work in paper millimetres, before travel optimization.
    """
    if not math.isfinite(gap) or gap < 0:
        raise ValueError('Distanța de unire trebuie să fie cel puțin zero')
    if gap == 0:return [list(p) for p in paths]
    remaining=[list(p) for p in paths];result=[]
    def direction(a,b):
        d=math.dist(a,b)
        return ((b[0]-a[0])/d,(b[1]-a[1])/d) if d>1e-9 else None
    def dot(a,b):return a[0]*b[0]+a[1]*b[1]
    def allowed(a,b):
        distance=math.dist(a[-1],b[0])
        if distance>gap:return False
        u=next((direction(p,a[-1]) for p in reversed(a[:-1]) if math.dist(p,a[-1])>.000001),None)
        v=next((direction(b[0],p) for p in b[1:] if math.dist(b[0],p)>.000001),None)
        if u is None or v is None or dot(u,v)<math.cos(math.radians(45)):return False
        bridge=direction(a[-1],b[0])
        return bridge is None or (dot(u,bridge)>=.5 and dot(v,bridge)>=.5)
    while remaining:
        chain=remaining.pop(0)
        while math.dist(chain[0],chain[-1])>1e-6:
            best=None
            for i,p in enumerate(remaining):
                if math.dist(p[0],p[-1])<=1e-6:continue
                for prepend in (False,True):
                    a=list(reversed(chain)) if prepend else chain
                    for reverse in (False,True):
                        b=list(reversed(p)) if reverse else p
                        if allowed(a,b):
                            candidate=(math.dist(a[-1],b[0]),i,prepend,reverse)
                            if best is None or candidate<best:best=candidate
            if best is None:break
            _,i,prepend,reverse=best;p=remaining.pop(i)
            if prepend:chain.reverse()
            if reverse:p.reverse()
            if math.dist(chain[-1],p[0])<1e-9:p=p[1:]
            chain.extend(p)
            if prepend:chain.reverse()
        result.append(chain)
    return result


def build_plan(cal, paths, start, lift=3, offset=0, dry=False, grouped=False):
    if not math.isfinite(lift) or not math.isfinite(offset) or lift < 0:
        raise ValueError('Ridicarea trebuie să fie pozitivă sau zero; Z trebuie să fie finit')
    if not cal.inside(start):
        raise ValueError('Adu manual pixul în INTERIORUL foii, la cel puțin 2 mm de margini. Aplicația nu traversează peretele suportului.')
    sx,sy,dz = cal.local(start)
    travel_offset = offset+lift
    park_offset = max(dz, travel_offset)
    r = float(start[3])
    commands = []
    operations = []
    current = np.array(start[:3])
    def add(xyz, kind='ptp'):
        nonlocal current
        xyz = np.asarray(xyz,dtype=float)
        distance = float(np.linalg.norm(xyz-current))
        count = max(1,math.ceil(distance/2))
        origin = current.copy()
        points = []
        for i in range(1,count+1):
            p = origin+(xyz-origin)*(i/count)
            if not cal.inside(p):
                raise ValueError('Traseul iese din interiorul sigur al foii')
            commands.append([*map(float,p),r])
            points.append(commands[-1])
        if distance > 1e-8:
            if kind == 'cp' and operations and operations[-1][0] == 'cp':
                operations[-1][1].extend(points)
            else:
                operations.append((kind, points if kind == 'cp' else [points[-1]]))
        current = xyz
    add(cal.world(sx,sy,park_offset))
    for index,path in enumerate(paths):
        if index == 0:
            add(cal.world(*path[0],park_offset), 'cp')
            add(cal.world(*path[0],travel_offset))
        add(cal.world(*path[0],travel_offset), 'cp')
        if not dry:
            add(cal.world(*path[0],offset))
        for xy in path[1:]:
            add(cal.world(*xy,travel_offset if dry else offset), 'cp')
        add(cal.world(*path[-1],travel_offset))
    add([current[0],current[1],cal.contact_z+park_offset])
    add(cal.world(sx,sy,park_offset), 'cp')
    return operations if grouped else commands


def build_laser_plan(cal, paths, start, laser_z, dry=False, grouped=False):
    """Same paper XY, separate absolute focal Z; all travel is laser-off.

    Never merge across a stroke boundary. First/final vertical moves are off,
    and return travel stays above the drawing plane inside the paper holder.
    """
    if not math.isfinite(laser_z):
        raise ValueError('Memorează un Z laser finit')
    if not paths or any(len(p)<2 for p in paths):
        raise ValueError('Laser: trasee insuficiente')
    if not cal.inside(start):
        raise ValueError('Adu unealta în interiorul foii, la cel puțin 2 mm de margini')
    sx,sy,_=cal.local(start)
    park_z=max(start[2],laser_z)
    current=np.asarray(start[:3],dtype=float)
    commands=[];operations=[]
    def add(xyz,kind):
        nonlocal current
        target=np.asarray(xyz,dtype=float);distance=float(np.linalg.norm(target-current))
        if distance<1e-8:return
        count=max(1,math.ceil(distance/2));points=[]
        for i in range(1,count+1):
            p=current+(target-current)*i/count
            if not cal.inside(p):raise ValueError('Traseul laser iese din interiorul foii')
            points.append([*map(float,p),float(start[3])])
        commands.extend(points)
        operations.append((kind,points if kind!='ptp' else [points[-1]]))
        current=target
    def world(xy,z):return cal.world(*xy,z-cal.contact_z)
    add(world((sx,sy),park_z),'ptp')
    add(world(paths[0][0],park_z),'cp')
    add(world(paths[0][0],laser_z),'ptp')
    for path in paths:
        add(world(path[0],laser_z),'cp')
        stroke=[]
        for xy in path[1:]:
            before=len(operations)
            add(world(xy,laser_z),'laser' if not dry else 'cp')
            if len(operations)>before:stroke.extend(operations.pop()[1])
        if stroke:operations.append(('cp' if dry else 'laser',stroke))
    add([current[0],current[1],park_z],'ptp')
    add(world((sx,sy),park_z),'cp')
    return operations if grouped else commands
