"""Conservative Magician 135/147 mm kinematics, validated against recorded poses.

Offsets are inferred from controller Cartesian/joint readings, not table height.
This is a reachability screen, not collision detection or external metrology.
"""
import math
import numpy as np

# Magician published J1 range; no additional arbitrary two-degree exclusion.
# https://www.dobot-robots.com/products/education/magician.html
JOINT_LIMITS = ((-120,120),(0,85),(-5,85),(-90,90))

class Kinematics:
    def __init__(self, samples):
        if len(samples) < 4:
            raise ValueError('Sunt necesare coordonatele și unghiurile celor patru colțuri')
        offsets=[]
        for p in samples:
            if len(p)!=8 or not all(math.isfinite(v) for v in p):
                raise ValueError('Probă de calibrare invalidă')
            x,y,z,r,j1,j2,j3,j4=p
            a,b,c=map(math.radians,(j1,j2,j3))
            offsets.append([x*math.cos(a)+y*math.sin(a)-135*math.sin(b)-147*math.cos(c),
                            -x*math.sin(a)+y*math.cos(a),
                            z-135*math.cos(b)+147*math.sin(c)])
            if abs(r-j1-j4)>.2:
                raise ValueError('Orientarea raportată nu corespunde modelului Magician')
        self.h,self.lateral,self.zoff=np.mean(offsets,axis=0)
        if np.max(np.linalg.norm(np.array(offsets)-[self.h,self.lateral,self.zoff],axis=1))>.5:
            raise ValueError('Modelul geometric nu corespunde citirilor. Recalibrează înainte de mișcare.')
        if abs(self.lateral)>5 or not -20<self.h<150 or abs(self.zoff)>150:
            raise ValueError('Offset unealtă neacceptat pentru pixul vertical')

    def inverse(self, p):
        x,y,z,r=p
        radius2=x*x+y*y-self.lateral*self.lateral
        if radius2<=0:
            raise ValueError('Punct inaccesibil lângă axa bazei')
        h=math.sqrt(radius2)
        base=math.atan2(y,x)-math.atan2(self.lateral,h)
        dh,dv=h-self.h,z-self.zoff
        dist=math.hypot(dh,dv)
        if dist<1 or dh<=0:
            raise ValueError('Punct prea aproape de bază')
        cosine=(135**2+dist**2-147**2)/(2*135*dist)
        if not -1<cosine<1:
            raise ValueError('Punct inaccesibil sau singular')
        theta=math.acos(cosine)+math.atan2(dv,dh)
        j2=90-math.degrees(theta)
        j3=math.degrees(math.atan2(135*math.sin(theta)-dv,dh-135*math.cos(theta)))
        j1=math.degrees(base)
        return [j1,j2,j3,r-j1]

    def check(self, p):
        joints=self.inverse(p)
        for axis,(q,(lo,hi)) in enumerate(zip(joints,JOINT_LIMITS),start=1):
            if not lo<=q<=hi:
                raise ValueError(f'Articulația J{axis}: {float(q):.1f}°; intervalul permis este {lo}…{hi}°. Repoziționează suportul și recalibrează.')
        combined=90+joints[1]-joints[2]
        if not 25<=combined<=140:
            raise ValueError('Traseu prea aproape de limita combinată a brațelor')

    def validate(self, plan, start, cancel):
        previous=np.asarray(start[:4])
        for target in plan:
            if cancel.is_set():
                raise ValueError('Verificare oprită')
            target=np.asarray(target)
            steps=max(1,math.ceil(np.linalg.norm(target[:3]-previous[:3])/.5))
            for i in range(steps+1):
                self.check(previous+(target-previous)*(i/steps))
            previous=target
