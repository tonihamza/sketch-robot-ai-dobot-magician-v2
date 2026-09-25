import math
import tempfile
import threading
import struct
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from dobot_draw.geometry import Calibration,build_plan,build_laser_plan,optimize,join_nearby
from dobot_draw.kinematics import Kinematics
from dobot_draw.svg import load_svg
from dobot_draw.robot import Robot,RobotError,packet


def cal():
    return Calibration([[190,-40,0],[270,-40,0],[270,40,0],[190,40,0]])


class GeometryTests(unittest.TestCase):
    def test_planners_accept_more_than_25000_commands(self):
        # Small in-bounds zigzag, no physical robot and no emission.
        path=[(40+i%2*2,40) for i in range(25100)]
        for planner in (lambda:build_plan(cal(),[path],[230,0,3,0]),
                        lambda:build_laser_plan(cal(),[path],[230,0,3,0],1)):
            commands=planner()
            self.assertGreater(len(commands),25000)
            self.assertTrue(all(cal().inside(p) for p in commands[::500]))

    def test_optimized_travel_never_worse_than_greedy_and_preserves_strokes(self):
        import random
        rng=random.Random(24)
        def travel(paths):
            return sum(math.dist(a,b) for a,b in zip([(0,0)]+[p[-1] for p in paths[:-1]], [p[0] for p in paths]))
        for _ in range(12):
            paths=[[(rng.random()*80,rng.random()*80) for _ in range(3)] for _ in range(30)]
            remaining=[p[:] for p in paths];greedy=[];pos=(0,0)
            while remaining:
                _,i,rev=min((math.dist(pos,p[-1] if rev else p[0]),i,rev) for i,p in enumerate(remaining) for rev in (False,True))
                p=remaining.pop(i)
                if rev:p.reverse()
                greedy.append(p);pos=p[-1]
            result=optimize(paths)
            self.assertLessEqual(travel(result),travel(greedy)+1e-8)
            canonical=lambda p:min(tuple(p),tuple(reversed(p)))
            self.assertCountEqual([canonical(p) for p in paths],[canonical(p) for p in result])

    def test_join_reversed_fragments_and_extend_both_ends(self):
        paths=[[(2,0),(3,0)],[(1.9,0),(1,0)],[(4,0),(3.1,0)]]
        joined=join_nearby(paths,.2)
        self.assertEqual(len(joined),1)
        self.assertEqual(joined[0][0],(1,0));self.assertEqual(joined[0][-1],(4,0))
        self.assertEqual(paths[1][0],(1.9,0))

    def test_join_does_not_bridge_parallel_closed_or_distant_strokes(self):
        for paths in ([[(0,0),(1,0)],[(0,.1),(1,.1)]],
                      [[(0,0),(1,0),(0,0)],[(1.1,0),(2,0)]],
                      [[(0,0),(1,0)],[(1.4,0),(2,0)]]):
            self.assertEqual(len(join_nearby(paths,.3)),2)
        self.assertEqual(len(join_nearby([[(0,0),(1,0)],[(1,0),(2,0)]],0)),2)

    def test_rotated_xy_preserves_scale_and_uses_highest_z(self):
        a=.6;u=np.array([math.cos(a),math.sin(a),0]);v=np.array([-math.sin(a),math.cos(a),.03]);v/=np.linalg.norm(v)
        origin=np.array([170,-60,-20]);p=[origin,origin+80*u,origin+80*u+80*v,origin+80*v]
        c=Calibration(p)
        self.assertAlmostEqual(np.linalg.norm(c.world(70,10)-c.world(10,10)),60)
        x,y,dz=c.local(c.world(30,40,3))
        np.testing.assert_allclose([x,y,dz],[30,40,3],atol=1e-8)
        self.assertAlmostEqual(c.world(30,40)[2],max(q[2] for q in p))

    def test_reject_bad_order_and_skew_xy(self):
        for p in ([[190,-40,0],[270,40,0],[270,-40,0],[190,40,0]],[[190,-40,0],[270,-40,0],[280,40,0],[200,40,0]]):
            with self.assertRaises(ValueError):Calibration(p)

    def test_spring_pen_negative_z_max_and_raw_corners_preserved(self):
        raw=[[190,-40,-24],[270,-40,-22],[270,40,-27],[190,40,-23]]
        c=Calibration(raw)
        self.assertEqual(c.corners,raw)
        self.assertEqual(raw[2][2],-27)
        self.assertEqual(c.contact_z,-22)
        self.assertEqual(c.z_spread,5)
        self.assertEqual(c.width,80)
        self.assertEqual(c.height,80)
        plan=build_plan(c,[[(5,5),(75,75)]],[230,0,-22,0],offset=-.5)
        self.assertTrue(any(abs(p[2]+22.5)<1e-8 for p in plan))
        self.assertTrue(all(p[2]>=-22.5 for p in plan))
        self.assertAlmostEqual(plan[-1][2],-19.5)

    def test_plan_interior_short_segments_and_return(self):
        c=cal();start=[230,0,1,0]
        plan=build_plan(c,[[(5,5),(75,5)],[(75,75),(5,75)]],start)
        prior=start
        for p in plan:
            self.assertTrue(c.inside(p));self.assertLessEqual(math.dist(prior[:3],p[:3]),2.000001);prior=p
        np.testing.assert_allclose(plan[-1],[230,0,3,0])
        self.assertTrue(any(p[2]==0 for p in plan))
        dry=build_plan(c,[[(5,5),(75,75)]],start,dry=True)
        self.assertTrue(all(p[2]>=1 for p in dry))

    def test_refuse_crossing_wall(self):
        for start in ([180,0,1,0],[180,0,40,0]):
            with self.assertRaises(ValueError):build_plan(cal(),[[(5,5),(75,75)]],start)

    def test_raised_start_travels_high_then_descends_only_at_stroke(self):
        c=cal();start=[230,0,40,0];paths=[[(5,5),(75,5)],[(75,75),(5,75)]]
        plan=build_plan(c,paths,start)
        first_descent=next(i for i,p in enumerate(plan) if p[2]<40-1e-8)
        np.testing.assert_allclose(plan[first_descent][:2],c.world(5,5)[:2])
        self.assertTrue(all(abs(p[2]-40)<1e-8 for p in plan[:first_descent]))
        np.testing.assert_allclose(plan[-1],start)
        # Drawing travel is calibration Z + lift; parking remains at start height.
        previous=start
        for p in plan:
            if math.dist(previous[:2],p[:2])>1e-8:
                self.assertTrue(any(abs(p[2]-z)<1e-8 for z in (0,3,40)))
                self.assertAlmostEqual(previous[2],p[2])
            previous=p
        dry=build_plan(c,paths,start,dry=True)
        self.assertTrue(all(p[2]>=3-1e-8 for p in dry))
        self.assertTrue(any(abs(p[2]-3)<1e-8 for p in dry))
        np.testing.assert_allclose(dry[-1],start)
        # Every departure from a completed stroke uses the low travel plane.
        np.testing.assert_allclose(c.world(75,5,3),next(p[:3] for p in plan if np.linalg.norm(np.array(p[:3])-c.world(75,5,3))<1e-8))

    def test_optimize_keeps_all_segments(self):
        p=[[(70,70),(60,60)],[(10,10),(5,5)]]
        result=optimize(p)
        self.assertEqual(result[0][0],(5,5));self.assertEqual(len(result),2)


class SVGTests(unittest.TestCase):
    def test_import_more_than_1500_paths_without_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/'many.svg'
            lines=''.join(f'<path d="M0 {i*.04}L5 {i*.04}"/>' for i in range(1601))
            f.write_text('<svg><g fill="none" stroke="black">'+lines+'</g></svg>')
            paths,_=load_svg(f,cal(),5,0)
            self.assertEqual(len(paths),1601)

    def test_short_fragments_are_joined_before_one_mm_filter(self):
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/'fragments.svg'
            f.write_text('<svg><g fill="none" stroke="black"><path d="M0 0L100 0"/><path d="M50 10L50.8 10"/><path d="M50.9 10L51.7 10"/></g></svg>')
            separate,_=load_svg(f,cal(),5,0)
            joined,_=load_svg(f,cal(),5,.15)
            self.assertEqual(len(separate),1)
            self.assertEqual(len(joined),2)
            for p in joined:self.assertGreaterEqual(sum(math.dist(a,b) for a,b in zip(p,p[1:])),1)

    def test_logo_has_reserved_top_left_space_and_respects_margins(self):
        file=Path(__file__).resolve().parent.parent/'examples/portrete/01_femeie_lineart.svg'
        original,_=load_svg(file,cal(),5,.3)
        branded,_=load_svg(file,cal(),5,.3,True)
        self.assertEqual(len(branded),len(original)+12)
        logo=[p for p in branded if max(y for x,y in p)<14]
        portrait=[p for p in branded if min(y for x,y in p)>=14-1e-7]
        self.assertEqual(len(logo),12)
        self.assertEqual(len(portrait),len(original))
        self.assertAlmostEqual(min(x for p in logo for x,y in p),5)
        self.assertAlmostEqual(max(x for p in logo for x,y in p),45)
        for p in branded:
            for x,y in p:self.assertTrue(5-1e-7<=x<=75+1e-7 and 5-1e-7<=y<=75+1e-7)

    def test_submillimetre_portrait_detail_is_filtered(self):
        p,_=self.load('<svg><g fill="none" stroke="black"><path d="M0 0L100 100"/><path d="M50 50L50.4 50.4"/></g></svg>')
        self.assertEqual(len(p),1)

    def test_unused_defs_do_not_draw_or_change_scaling(self):
        p,info=self.load('<svg><defs><path d="M0 0L900 900"/><clipPath id="unused"><rect width="900" height="900"/></clipPath></defs><path d="M0 0L10 5"/></svg>')
        self.assertEqual(len(p),1)
        self.assertAlmostEqual(info['width'],70)
        self.assertAlmostEqual(info['height'],35)

    def test_styles_inside_defs_are_preserved(self):
        p,info=self.load('<svg><defs><style>.hide {display:none} .line {fill:none;stroke:black}</style></defs><path class="hide" d="M0 0L900 900"/><path class="line" d="M0 0L10 5"/></svg>')
        self.assertEqual(len(p),1)
        self.assertAlmostEqual(info['height'],35)

    def test_referenced_clipping_still_rejected(self):
        with self.assertRaises(ValueError):
            self.load('<svg><defs><clipPath id="c"><rect width="2" height="2"/></clipPath></defs><path clip-path="url(#c)" d="M0 0L10 10"/></svg>')

    def load(self,body):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.svg';path.write_text(body,encoding='utf-8')
            return load_svg(path,cal())

    def test_units_transforms_curves_and_separate_paths(self):
        p,info=self.load('<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="80mm" viewBox="0 0 80 80"><g transform="translate(5 7) scale(2)" fill="none" stroke="black"><path d="M0 0 C0 20 20 20 20 0 M30 0 L30 10"/></g></svg>')
        self.assertEqual(len(p),2);self.assertAlmostEqual(info['width'],70)
        self.assertLess(info['height'],70)

    def test_white_background_ignored(self):
        p,info=self.load('<svg xmlns="http://www.w3.org/2000/svg"><rect width="500" height="500" fill="white"/><path d="M0 0 L10 10" fill="none" stroke="black"/></svg>')
        self.assertEqual(len(p),1);self.assertAlmostEqual(info['width'],70)

    def test_unsupported_not_silently_ignored(self):
        for body in ('<svg><text>Hello</text></svg>','<svg><image href="https://example.com/a.png"/></svg>','<!DOCTYPE svg><svg/>','<svg><path d="M0 0L1 1" clip-path="url(#a)"/></svg>'):
            with self.assertRaises(ValueError):self.load(body)

    def test_tiny_paths_filtered_and_fill_warned(self):
        p,info=self.load('<svg><path d="M0 0L100 100 M50 50 L50.001 50.001"/></svg>')
        self.assertEqual(len(p),1);self.assertTrue(info['warnings'])


class KinematicTests(unittest.TestCase):
    def samples(self):
        points=[]
        for j1,j2,j3 in [(0,10,10),(20,30,20),(-10,20,40),(10,40,30)]:
            a,b,c=map(math.radians,(j1,j2,j3));h=135*math.sin(b)+147*math.cos(c)+61;z=135*math.cos(b)-147*math.sin(c)
            points.append([h*math.cos(a),h*math.sin(a),z,0,j1,j2,j3,-j1])
        return points

    def test_inverse_roundtrip(self):
        samples=self.samples();model=Kinematics(samples)
        for p in samples:np.testing.assert_allclose(model.inverse(p[:4]),p[4:],atol=1e-6);model.check(p[:4])

    def test_inconsistent_calibration_refused(self):
        samples=self.samples();samples[0][2]+=4
        with self.assertRaises(ValueError):Kinematics(samples)

    def test_limit_and_cancel(self):
        model=Kinematics(self.samples())
        with self.assertRaises(ValueError):model.check([600,0,0,0])
        stop=threading.Event();stop.set()
        with self.assertRaises(ValueError):model.validate([[220,0,90,0]],[220,0,85,0],stop)

    def test_side_workspace_allowed_but_base_edge_rejected(self):
        model=Kinematics(self.samples())
        for degrees in (97.3,117,-117,118.1,-118.1,119.9,-119.9):
            a=math.radians(degrees)
            model.check([230*math.cos(a),230*math.sin(a),80,degrees])
        for degrees in (120.1,-120.1):
            a=math.radians(degrees)
            with self.assertRaisesRegex(ValueError,'J1:'):
                model.check([230*math.cos(a),230*math.sin(a),80,degrees])


class TransportTests(unittest.TestCase):
    def test_cp_prefills_and_waits_for_barrier(self):
        r=Robot.__new__(Robot);calls=[];next_index=0;executed=0;running=False
        def rpc(cmd,control=0,data=b''):
            nonlocal next_index,executed,running
            calls.append((cmd,data))
            if cmd==241:running=False
            if cmd==240:running=True
            if cmd==247:return struct.pack('<I',64)
            if cmd in (91,110):
                next_index+=1
                return struct.pack('<Q',next_index)
            if cmd==246:
                self.assertTrue(running)
                executed=min(executed+4,next_index)
                return struct.pack('<Q',executed)
            return b''
        progress=[]
        with patch.object(r,'rpc',side_effect=rpc),patch.object(r,'check_clear'):
            r.continuous([[220+i,0,0,0] for i in range(40)],threading.Event(),progress.append)
        start=next(i for i,c in enumerate(calls) if c[0]==240)
        self.assertEqual(sum(c[0]==91 for c in calls[:start]),16)
        self.assertEqual(sum(c[0]==91 for c in calls),40)
        self.assertEqual(executed,41)
        self.assertEqual(progress[-1],40)
        payload=next(c[1] for c in calls if c[0]==91)
        self.assertEqual(struct.unpack('<B4f',payload),(1,220,0,0,0))

    def test_cp_cancel_during_prefill_stops_submission(self):
        r=Robot.__new__(Robot);cancel=threading.Event();moves=[]
        def rpc(cmd,*args):
            if cmd==247:return struct.pack('<Q',64)
            if cmd==91:
                moves.append(cmd);cancel.set();return struct.pack('<Q',1)
            return b''
        with patch.object(r,'rpc',side_effect=rpc):
            with self.assertRaises(RobotError):r.continuous([[220,0,0,0]]*40,cancel)
        self.assertEqual(len(moves),1)

    def test_grouped_plan_vertical_ptp_and_continuous_lines(self):
        start=[230,0,10,0]
        operations=build_plan(cal(),[[(5,5),(75,5),(75,75)]],start,grouped=True)
        previous=start
        for kind,points in operations:
            if kind=='ptp':
                self.assertEqual(len(points),1)
                np.testing.assert_allclose(previous[:2],points[0][:2])
            else:
                self.assertTrue(all(abs(p[2]-previous[2])<1e-8 for p in points))
            previous=points[-1]
        self.assertEqual(previous,start)

    def test_packet_official_getpose(self):
        self.assertEqual(packet(10),bytes.fromhex('aaaa020a00f6'))

    def test_corrupt_response_latches_fault(self):
        class Fake:
            in_waiting=0
            def write(self,p):pass
            def read(self,n):
                self.read=lambda n:b''
                return bytes.fromhex('aaaa020a00ff')
        robot=Robot.__new__(Robot);robot.lock=threading.RLock();robot.serial=Fake();robot.fault=False;robot.buffer=bytearray()
        with self.assertRaises(RobotError):robot.rpc(10)
        self.assertTrue(robot.fault)
        with self.assertRaises(RobotError):robot.rpc(84,3)

    def test_cancel_prevents_motion_submission(self):
        r=Robot.__new__(Robot);e=threading.Event();e.set()
        with patch.object(r,'rpc') as rpc:
            with self.assertRaises(RobotError):r.move([1,2,3,0],e)
            rpc.assert_not_called()

    def test_unknown_limit_echo_not_accepted(self):
        r=Robot.__new__(Robot)
        with patch.object(r,'rpc',return_value=b'\0'*17):
            with self.assertRaises(RobotError):r.reachable([1,2,3,0])

    def test_move_waits_for_own_queue_index(self):
        r=Robot.__new__(Robot);stop=threading.Event()
        replies=[struct.pack('<Q',7),struct.pack('<Q',6),struct.pack('<Q',7)]
        with patch.object(r,'rpc',side_effect=replies) as rpc:
            r.move([220,0,90,0],stop)
            self.assertEqual([a.args[0] for a in rpc.call_args_list],[84,246,246])
            self.assertEqual(rpc.call_args_list[0].args[1],3)


if __name__=='__main__':unittest.main()
