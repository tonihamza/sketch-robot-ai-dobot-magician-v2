import math
import tempfile
import unittest
from pathlib import Path
from dobot_draw.curves import rounded_segments, flatten_segments, svg_commands
from dobot_draw.svg import load_svg
from dobot_draw.geometry import Calibration


def distance_to_segment(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)) if den else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)


class CurveTests(unittest.TestCase):
    def test_rounding_is_bounded_and_keeps_endpoints(self):
        source=[(0,0),(5,0),(9,2),(12,5)]
        segments=rounded_segments(source,.08)
        self.assertTrue(any(control is not None for _,control,_ in segments))
        sampled=flatten_segments(segments,.0001)
        self.assertEqual(sampled[0],source[0]);self.assertEqual(sampled[-1],source[-1])
        for p in sampled:
            self.assertLessEqual(min(distance_to_segment(p,a,b) for a,b in zip(source,source[1:])),.08+1e-9)
            self.assertTrue(0<=p[0]<=12 and 0<=p[1]<=5)
        # Adjacent line/quadratic tangents agree, not just their endpoints.
        for (a,b,c),(d,e,f) in zip(segments,segments[1:]):
            self.assertEqual(c,d)
            before=b or a;after=e or f
            u=(c[0]-before[0],c[1]-before[1]);v=(after[0]-d[0],after[1]-d[1])
            self.assertAlmostEqual(u[0]*v[1]-u[1]*v[0],0,places=10)

    def test_corners_branches_closed_anchor_and_reversals_are_preserved(self):
        square=[(0,0),(5,0),(5,5),(0,5),(0,0)]
        self.assertEqual(flatten_segments(rounded_segments(square,.08),.025),square)
        backtrack=[(0,0),(5,0),(0,0)]
        self.assertEqual(flatten_segments(rounded_segments(backtrack,.08),.025),backtrack)
        for branch in [[(0,0),(3,1),(5,1)],[(0,0),(-3,1),(-5,1)]]:
            self.assertEqual(flatten_segments(rounded_segments(branch,.08),.025)[0],(0,0))
        closed=[(0,0),(3,0),(5,1),(6,4),(0,0)]
        points=flatten_segments(rounded_segments(closed,.08),.025)
        self.assertEqual(points[0],closed[0]);self.assertEqual(points[-1],closed[-1])

    def test_duplicates_and_disabled_smoothing(self):
        source=[(0,0),(0,0),(5,0),(10,2)]
        self.assertEqual(flatten_segments(rounded_segments(source,0),.025),[(0,0),(5,0),(10,2)])
        self.assertEqual(rounded_segments([(0,0),(0,0)],.08),[])

    def test_adaptive_subdivision_bounds_quadratic_chord_error(self):
        segments=[((0,0),(5,8),(10,0))]
        points=flatten_segments(segments,.025)
        for i in range(1001):
            t=i/1000;p=(10*t,16*t*(1-t))
            self.assertLessEqual(min(distance_to_segment(p,a,b) for a,b in zip(points,points[1:])),.025+1e-9)

    def test_exported_curves_and_legacy_polylines_import_as_single_strokes(self):
        source=[(0,0),(20,0),(40,8),(60,20)]
        cal=Calibration([[190,-40,0],[270,-40,0],[270,40,0],[190,40,0]])
        with tempfile.TemporaryDirectory() as temp:
            for tolerance in (0,.08):
                d=svg_commands(rounded_segments(source,tolerance))
                if tolerance:self.assertIn('Q ',d)
                p=Path(temp)/'curve.svg'
                p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}" fill="none" stroke="black"/></svg>')
                paths,info=load_svg(p,cal,5)
                self.assertEqual(len(paths),1)
                self.assertGreater(len(paths[0]),len(source))
                self.assertTrue(all(5-1e-8<=x<=75+1e-8 and 5-1e-8<=y<=75+1e-8 for x,y in paths[0]))
