"""Small, bounded quadratic blends for raster-derived polylines.

All control points stay in the original polyline's convex hull. Endpoints,
branch connections and turns of 60 degrees or more remain unchanged.
"""
import math


def rounded_segments(points, tolerance):
    """Return (start, control-or-None, end) segments, in source units.

    Only shallow turns are blended. The distance to the original polyline
    is bounded by tolerance; no gaps or separate strokes are joined here.
    A closed path keeps its original start/end anchor as well.
    """
    clean=[]
    for p in points:
        p=tuple(map(float,p))
        if not clean or math.dist(clean[-1],p)>1e-10:clean.append(p)
    if len(clean)<2:return []
    if not math.isfinite(tolerance) or tolerance<0:
        raise ValueError('Toleranța curbelor trebuie să fie finită și nenegativă')
    segments=[];current=clean[0]
    def line(end):
        nonlocal current
        if math.dist(current,end)>1e-10:segments.append((current,None,end))
        current=end
    for a,b,c in zip(clean,clean[1:],clean[2:]):
        la=math.dist(a,b);lb=math.dist(b,c)
        u=((b[0]-a[0])/la,(b[1]-a[1])/la)
        v=((c[0]-b[0])/lb,(c[1]-b[1])/lb)
        cosine=max(-1.,min(1.,u[0]*v[0]+u[1]*v[1]))
        if tolerance==0 or cosine<=.5 or cosine>1-1e-10:
            line(b);continue
        sine_half=math.sqrt((1-cosine)/2)
        cut=min(la/2,lb/2,tolerance/sine_half)
        entry=(b[0]-cut*u[0],b[1]-cut*u[1])
        end=(b[0]+cut*v[0],b[1]+cut*v[1])
        line(entry);segments.append((entry,b,end));current=end
    line(clean[-1])
    return segments


def flatten_segments(segments, tolerance):
    """Adaptive quadratic subdivision, bounded by chord error, not pixel steps."""
    if not math.isfinite(tolerance) or tolerance<=0:
        raise ValueError('Toleranța de discretizare trebuie să fie pozitivă')
    if not segments:return []
    points=[segments[0][0]]
    for start,control,end in segments:
        if control is None:
            points.append(end);continue
        stack=[(start,control,end)]
        while stack:
            a,b,c=stack.pop()
            dx,dy=c[0]-a[0],c[1]-a[1];den=dx*dx+dy*dy
            t=max(0.,min(1.,((b[0]-a[0])*dx+(b[1]-a[1])*dy)/den)) if den else 0
            distance=math.hypot(b[0]-a[0]-t*dx,b[1]-a[1]-t*dy)
            if distance/2<=tolerance:
                points.append(c);continue
            ab=((a[0]+b[0])/2,(a[1]+b[1])/2)
            bc=((b[0]+c[0])/2,(b[1]+c[1])/2)
            mid=((ab[0]+bc[0])/2,(ab[1]+bc[1])/2)
            stack.extend([(mid,bc,c),(a,ab,mid)])
    return points


def svg_commands(segments):
    if not segments:return ''
    start=segments[0][0]
    commands=[f'M {start[0]:.4f} {start[1]:.4f}']
    for _,control,end in segments:
        if control is None:commands.append(f'L {end[0]:.4f} {end[1]:.4f}')
        else:commands.append(f'Q {control[0]:.4f} {control[1]:.4f} {end[0]:.4f} {end[1]:.4f}')
    return ' '.join(commands)
