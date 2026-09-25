import io
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path as FilePath
from svgelements import SVG, Path, Shape, Move
from .geometry import optimize, join_nearby


def simplify(points, epsilon=.05):
    # Iterative RDP: avoids recursion limits on portraits.
    if len(points)<3:
        return points
    keep={0,len(points)-1}
    stack=[(0,len(points)-1)]
    while stack:
        a,b=stack.pop()
        x,y=points[a]; dx=points[b][0]-x;dy=points[b][1]-y
        den=dx*dx+dy*dy
        best,k=0,None
        for i in range(a+1,b):
            px,py=points[i]
            t=max(0,min(1,((px-x)*dx+(py-y)*dy)/den)) if den else 0
            d=math.hypot(px-x-t*dx,py-y-t*dy)
            if d>best:
                best,k=d,i
        if best>epsilon:
            keep.add(k);stack.extend([(a,k),(k,b)])
    return [points[i] for i in sorted(keep)]


def load_svg(filename, cal, margin=5, join_gap=0, brand=False):
    if not math.isfinite(margin) or margin < 0 or 2*margin >= min(cal.width,cal.height,80):
        raise ValueError('Marginea trebuie să fie cel puțin zero și să lase loc desenului pe foaie')
    raw=FilePath(filename).read_bytes()
    if len(raw)>2_000_000:
        raise ValueError('SVG prea mare (maxim 2 MB)')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Declarațiile DTD/entități nu sunt acceptate')
    root=ET.fromstring(raw)
    # Unused definitions are not drawable content. Preserve embedded styles,
    # but remove definition geometry so it can never become a stray pen path.
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag.split('}')[-1] in ('defs','metadata'):
                index=list(parent).index(child)
                for style in child.iter():
                    if style.tag.split('}')[-1]=='style':
                        parent.insert(index,ET.fromstring(ET.tostring(style)));index+=1
                parent.remove(child)
    allowed={'svg','g','path','line','polyline','polygon','circle','ellipse','rect','title','desc','style'}
    for el in root.iter():
        tag=el.tag.split('}')[-1]
        if tag not in allowed:
            raise ValueError(f'Element SVG neacceptat: {tag}. Exportă un SVG simplu cu textul convertit în trasee.')
        if tag=='style':
            css=re.sub(r'/\*.*?\*/','',el.text or '',flags=re.S)
            if re.search(r'url\s*\(|@|clip-path\s*:|mask\s*:|filter\s*:',css,re.I):
                raise ValueError('Stilul SVG folosește referințe sau efecte care trebuie convertite în trasee')
            for selector in re.findall(r'([^{}]+)\{',css):
                if any(not re.fullmatch(r'(?:\*|[.#]?[\w-]+)',part.strip()) for part in selector.split(',')):
                    raise ValueError('Selector CSS complex: exportă stilurile ca atribute SVG')
        for k,v in el.attrib.items():
            if k.split('}')[-1] in ('href','clip-path','mask','filter') or 'url(' in v.lower():
                raise ValueError('Referințele, măștile și filtrele SVG nu sunt acceptate')
    svg=SVG.parse(io.BytesIO(ET.tostring(root)),reify=True,on_error='raise')
    shapes=[]
    warnings=set()
    for el in svg.elements():
        if not isinstance(el,Shape):
            continue
        if el.values.get('visibility') in ('hidden','collapse') or el.values.get('display')=='none':
            continue
        if float(el.values.get('opacity',1))==0:
            continue
        stroke=getattr(el,'stroke',None);fill=getattr(el,'fill',None)
        has_stroke=stroke is not None and stroke.value is not None and stroke.alpha>0 and stroke.rgb!=0xffffff
        has_fill=fill is not None and fill.value is not None and fill.alpha>0 and fill.rgb!=0xffffff
        if not has_stroke and not has_fill:
            continue
        if has_fill:
            warnings.add('Suprafețele umplute sunt desenate doar pe contur; nu se generează hașuri sau trasee centrale.')
        p=Path(el)
        if p.bbox() is not None:
            shapes.append(p)
    if not shapes:
        raise ValueError('SVG fără trasee vizibile de desenat')
    boxes=[p.bbox() for p in shapes]
    xmin=min(b[0] for b in boxes);ymin=min(b[1] for b in boxes)
    width=max(b[2] for b in boxes)-xmin;height=max(b[3] for b in boxes)-ymin
    if not all(math.isfinite(v) for v in (xmin,ymin,width,height)) or max(width,height)<1e-9:
        raise ValueError('Dimensiuni SVG invalide')
    aw=min(cal.width,80)-2*margin;ah=min(cal.height,80)-2*margin
    scale=min(aw/width if width else float('inf'),ah/height if height else float('inf'))
    ox=(cal.width-width*scale)/2;oy=(cal.height-height*scale)/2
    def xy(p):
        return ((p.x-xmin)*scale+ox,(p.y-ymin)*scale+oy)
    paths=[];total=0
    for shape in shapes:
        for sub in shape.as_subpaths():
            points=[]
            for segment in sub:
                if isinstance(segment,Move):
                    continue
                n=max(1,math.ceil(segment.length(error=1e-5)*scale/.25))
                total+=n
                if total>200_000:
                    raise ValueError('SVG prea complex pentru această aplicație; simplifică traseele')
                if not points:
                    points.append(xy(segment.point(0)))
                points.extend(xy(segment.point(i/n)) for i in range(1,n+1))
            if len(points)>1:
                points=simplify(points)
                if sum(math.dist(a,b) for a,b in zip(points,points[1:]))>=.05:
                    paths.append(points)
    if not paths:
        raise ValueError('Nu au rămas trasee după filtrarea detaliilor sub 0,05 mm')
    before=len(paths)
    paths=join_nearby(paths,join_gap)
    joined=before-len(paths)
    if brand:
        # Reserve a header above the portrait. Layout uses the final physical
        # drawing area; logo paths never participate in portrait gap joining.
        available_w=min(cal.width,80)-2*margin
        available_h=min(cal.height,80)-2*margin
        left=(cal.width-available_w)/2
        top=(cal.height-available_h)/2
        header=min(9,available_h*.2)
        xmin=min(x for p in paths for x,y in p);xmax=max(x for p in paths for x,y in p)
        ymin=min(y for p in paths for x,y in p);ymax=max(y for p in paths for x,y in p)
        factor=min(available_w/(xmax-xmin) if xmax>xmin else 1,
                   (available_h-header)/(ymax-ymin) if ymax>ymin else 1)
        px=left+(available_w-(xmax-xmin)*factor)/2
        py=top+header+(available_h-header-(ymax-ymin)*factor)/2
        paths=[[(px+(x-xmin)*factor,py+(y-ymin)*factor) for x,y in p] for p in paths]
        logo_file=FilePath(__file__).resolve().parent.parent/'examples/logo/laptop-aid-o-singura-linie.svg'
        logo,_=load_svg(logo_file,cal,5,0,False)
        lx=min(x for p in logo for x,y in p);rx=max(x for p in logo for x,y in p)
        ly=min(y for p in logo for x,y in p);ry=max(y for p in logo for x,y in p)
        logo_scale=min(40,available_w)/(rx-lx)
        logo_scale=min(logo_scale,header*.6/(ry-ly))
        paths.extend([[(left+(x-lx)*logo_scale,top+(y-ly)*logo_scale) for x,y in p] for p in logo])
    # Filter in final physical millimetres, after joins and portrait resizing.
    # Short fragments that form a longer joined stroke remain useful.
    count_before_filter=len(paths)
    paths=[p for p in paths if sum(math.dist(a,b) for a,b in zip(p,p[1:]))>=1-1e-9]
    removed=count_before_filter-len(paths)
    if not paths:
        raise ValueError('Nu există trasee de cel puțin 1 mm la dimensiunea aleasă')
    paths=optimize(paths)
    length=sum(math.dist(a,b) for p in paths for a,b in zip(p,p[1:]))
    output_width=max(x for p in paths for x,y in p)-min(x for p in paths for x,y in p)
    output_height=max(y for p in paths for x,y in p)-min(y for p in paths for x,y in p)
    return paths,dict(width=output_width,height=output_height,length=length,joined=joined,removed=removed,warnings=sorted(warnings))
