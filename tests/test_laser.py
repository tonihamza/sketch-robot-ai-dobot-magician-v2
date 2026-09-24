import math
import struct
import threading
import unittest
from unittest.mock import patch
from dobot_draw.geometry import Calibration,build_laser_plan
from dobot_draw.robot import Robot,RobotError


class LaserTests(unittest.TestCase):
    def test_same_xy_fixed_z_separate_strokes_and_off_return(self):
        cal=Calibration([[190,-40,0],[270,-40,0],[270,40,0],[190,40,0]])
        paths=[[(5,5),(75,5)],[(75,75),(5,75)]]
        start=[230,0,30,0]
        operations=build_laser_plan(cal,paths,start,12,grouped=True)
        strokes=[p for kind,p in operations if kind=='laser']
        self.assertEqual(len(strokes),2)
        self.assertTrue(all(p[2]==12 for stroke in strokes for p in stroke))
        self.assertEqual(strokes[0][-1][:3],list(cal.world(75,5,12)))
        self.assertEqual(operations[-1][1][-1],start)
        self.assertNotEqual(operations[0][0],'laser')
        self.assertTrue(all(kind!='laser' for kind,_ in build_laser_plan(cal,paths,start,12,dry=True,grouped=True)))
        with self.assertRaises(ValueError):build_laser_plan(cal,paths,start,float('nan'))

    def test_cple_embeds_power_then_queued_off_before_barrier(self):
        robot=Robot.__new__(Robot);robot.laser_session=True
        calls=[];queued=0;executed=0
        def rpc(command,control=0,data=b'',**kwargs):
            nonlocal queued,executed
            calls.append((command,control,data))
            if command==247:return struct.pack('<I',64)
            if control==3:
                queued+=1;return struct.pack('<Q',queued)
            if command==246:
                executed=min(executed+4,queued);return struct.pack('<Q',executed)
            return b''
        points=[[220+i,0,12,0] for i in range(35)]
        with patch.object(robot,'rpc',side_effect=rpc),patch.object(robot,'check_clear'):
            robot.continuous_laser(points,17,threading.Event())
        queue=[c for c in calls if c[1]==3]
        self.assertEqual([c[0] for c in queue], [92]*35+[61,110])
        self.assertTrue(all(struct.unpack('<B4f',c[2])[-1]==17 for c in queue[:-2]))
        self.assertEqual(queue[-2][2],b'\x01\x00')
        self.assertEqual(calls[-1],(61,1,b'\x01\x00'))

    def test_laser_cancellation_and_stop_attempt_off_even_after_fault(self):
        robot=Robot.__new__(Robot);robot.laser_session=True
        cancel=threading.Event();cancel.set()
        with patch.object(robot,'rpc',return_value=b'') as rpc:
            with self.assertRaises(RobotError):robot.continuous_laser([[1,2,3,0]],10,cancel)
            self.assertEqual(rpc.call_args.args,(61,1,b'\x01\x00'))
            self.assertTrue(rpc.call_args.kwargs['allow_fault'])
        calls=[]
        def rpc(command,*args,**kwargs):
            calls.append(command)
            if command==242:raise RobotError('USB error')
            return b''
        with patch.object(robot,'rpc',side_effect=rpc):
            with self.assertRaises(RobotError):robot.stop()
        self.assertEqual(calls,[61,242,245,61])

    def test_invalid_power_never_submits(self):
        robot=Robot.__new__(Robot);robot.laser_session=True
        for power in (0,-1,101,float('nan')):
            with patch.object(robot,'rpc') as rpc:
                with self.assertRaises(RobotError):robot.continuous_laser([[1,2,3,0]],power,threading.Event())
                rpc.assert_not_called()
