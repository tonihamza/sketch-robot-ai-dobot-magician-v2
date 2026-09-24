import math
import struct
import threading
import unittest
from unittest.mock import patch
from dobot_draw.geometry import Calibration,build_laser_plan
from dobot_draw.robot import Robot,RobotError


class LaserTests(unittest.TestCase):
    def focus_robot(self):
        robot=Robot.__new__(Robot);robot.fault=False
        calls=[];queued=0
        def rpc(command,control=0,data=b'',**kwargs):
            nonlocal queued
            calls.append((command,control,data))
            if control==3:
                queued+=1;return struct.pack('<Q',queued)
            if command==246:return struct.pack('<Q',queued)
            if command==61 and control==0:return b'\x01\x00'
            return b''
        robot.rpc=rpc
        robot.check_clear=lambda:None
        return robot,calls

    def test_focus_queues_timed_off_before_start_without_motion_or_power_command(self):
        robot,calls=self.focus_robot()
        started=[]
        robot.focus_laser(threading.Event(),lambda:started.append(True))
        program=[c for c in calls if c[1]==3]
        self.assertEqual(program,[(61,3,b'\x01\x01'),(110,3,struct.pack('<I',1000)),
                                  (61,3,b'\x01\x00'),(110,3,struct.pack('<I',1))])
        self.assertLess(calls.index(program[-1]),calls.index((240,1,b'')))
        self.assertEqual(sum(c[0]==240 for c in calls),1)
        self.assertFalse(any(c[0] in (84,91,92) for c in calls))
        self.assertEqual([c[0] for c in calls[-5:]],[61,242,245,61,61])
        self.assertEqual(started,[True])

    def test_focus_stop_before_start_and_during_pulse_always_clears_and_turns_off(self):
        for before in (True,False):
            with self.subTest(before=before):
                robot,calls=self.focus_robot();cancel=threading.Event()
                if before:cancel.set()
                robot.focus_laser(cancel,cancel.set)
                self.assertEqual(sum(c[0]==240 for c in calls),0 if before else 1)
                self.assertEqual(calls[-2],(61,1,b'\x01\x00'))
                self.assertEqual(calls[-1],(61,0,b''))

    def test_focus_requires_complete_ordered_queue_before_any_emission(self):
        for failure in ('missing_off_ack','unordered','alarm'):
            with self.subTest(failure=failure):
                robot,calls=self.focus_robot();original=robot.rpc
                def rpc(command,control=0,data=b'',**kwargs):
                    result=original(command,control,data,**kwargs)
                    if command==61 and control==3 and data==b'\x01\x00':
                        return b'' if failure=='missing_off_ack' else struct.pack('<Q',1)
                    return result
                robot.rpc=rpc
                if failure=='alarm':robot.check_clear=lambda:(_ for _ in ()).throw(RobotError('alarm'))
                with self.assertRaises(RobotError):robot.focus_laser(threading.Event())
                self.assertFalse(any(c[0]==240 for c in calls))
                self.assertEqual(calls[-2],(61,1,b'\x01\x00'))

    def test_focus_timeout_or_usb_fault_never_retries_on_and_attempts_off(self):
        for failure in ('timeout','usb','start_ack','alarm'):
            with self.subTest(failure=failure):
                robot,calls=self.focus_robot();original=robot.rpc
                def rpc(command,control=0,data=b'',**kwargs):
                    result=original(command,control,data,**kwargs)
                    if command==240 and failure=='start_ack':raise RobotError('Start ACK lost')
                    if command==246:
                        if failure=='usb':raise RobotError('USB lost')
                        return struct.pack('<Q',0)
                    return result
                robot.rpc=rpc
                with patch('dobot_draw.robot.time.monotonic',side_effect=[0,3]):
                    def started():
                        if failure=='alarm':robot.check_clear=lambda:(_ for _ in ()).throw(RobotError('alarm'))
                    with self.assertRaises(RobotError):robot.focus_laser(threading.Event(),started)
                self.assertEqual(sum(c==(61,3,b'\x01\x01') for c in calls),1)
                self.assertEqual(sum(c[0]==240 for c in calls),1)
                self.assertEqual(calls[-2],(61,1,b'\x01\x00'))

    def test_focus_unconfirmed_off_invalidates_connection(self):
        robot,calls=self.focus_robot();original=robot.rpc;reads=0
        def rpc(command,control=0,data=b'',**kwargs):
            nonlocal reads
            result=original(command,control,data,**kwargs)
            if command==61 and control==0:
                reads+=1
                if reads==2:return b'\x01\x01'
            return result
        robot.rpc=rpc
        with self.assertRaisesRegex(RobotError,'Întrerupe alimentarea'):robot.focus_laser(threading.Event())
        self.assertTrue(robot.fault)

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
