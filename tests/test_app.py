"""Simulated integration: real planner/importer/UI worker, no hardware port."""
import tempfile
import time
import threading
import gc
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from dobot_draw.app import App,ROOT
from dobot_draw.geometry import Calibration
from dobot_draw.kinematics import Kinematics
import test_core


class FakeRobot:
    fault=False
    def __init__(self,model):self.model=model;self.current=[230,0,0,0];self.moves=[];self.stops=0
    def pose(self):return self.current+self.model.inverse(self.current)
    def check_clear(self):pass
    def rpc(self,*args):return b'tool'
    def prepare(self,speed,z_speed):pass
    def stop(self):self.stops+=1
    def move(self,p,cancel):self.current=list(p);self.moves.append(list(p))
    def continuous(self,points,cancel,progress):
        for i,p in enumerate(points):self.move(p,cancel);progress(i+1)
    def close(self):pass


class AppTests(unittest.TestCase):
    def setUp(self):
        # Collect old Tk fixtures on the UI thread before worker allocations.
        gc.collect()

    def test_focus_requires_explicit_laser_confirmation_and_needs_no_svg_or_calibration(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror') as error:
            root=tk.Tk();root.withdraw();app=App(root)
            try:
                from unittest.mock import Mock
                app.robot=Mock(fault=False)
                app.focus_laser();app.robot.focus_laser.assert_not_called()
                app.tool_mode.set('Laser');app.tool_changed()
                app.focus_laser();app.robot.focus_laser.assert_not_called()
                self.assertEqual(error.call_count,2)
                app.laser_safe.set(True);app.focus_laser()
                deadline=time.monotonic()+3
                while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                app.robot.focus_laser.assert_called_once()
                self.assertFalse(app.focus_active);self.assertIn('STINS',app.focus_status.get())
                self.assertIsNone(app.file);self.assertIsNone(app.cal)
                app.robot.move.assert_not_called();app.robot.continuous_laser.assert_not_called()
            finally:app.close()

    def test_focus_blocks_jobs_and_can_be_stopped_disconnected_or_closed(self):
        for action in ('stop','disconnect','close','tool_change'):
            with self.subTest(action=action),tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror') as error:
                root=tk.Tk();root.withdraw();app=App(root)
                entered=threading.Event();finished=threading.Event();closed=False
                try:
                    from unittest.mock import Mock
                    robot=Mock(fault=False)
                    def focus(cancel,started):
                        started();entered.set();cancel.wait(3);finished.set()
                    robot.focus_laser.side_effect=focus;app.robot=robot
                    app.tool_mode.set('Laser');app.tool_changed();app.laser_safe.set(True)
                    app.focus_laser();self.assertTrue(entered.wait(1))
                    app.focus_laser();app.capture_laser_z();app.run(False)
                    robot.focus_laser.assert_called_once();robot.pose.assert_not_called()
                    app.ai_busy=True;app.ai_cancel.clear()
                    if action=='stop':app.stop()
                    elif action=='disconnect':app.connect()
                    elif action=='tool_change':app.tool_mode.set('Pix');app.tool_changed()
                    else:
                        app.close();self.assertTrue(app.ai_cancel.is_set());app.ai_busy=False
                    if action!='close':self.assertFalse(app.ai_cancel.is_set());app.ai_busy=False
                    self.assertTrue(finished.wait(1))
                    deadline=time.monotonic()+3
                    while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    self.assertFalse(app.busy);self.assertFalse(app.focus_active)
                    self.assertFalse(error.called)
                    if action=='disconnect':self.assertIsNone(app.robot);robot.close.assert_called_once()
                    elif action=='tool_change':self.assertEqual(app.tool_mode.get(),'Laser')
                    elif action=='close':closed=True;robot.close.assert_called_once()
                finally:
                    if not closed:app.ai_busy=False;app.close()

    def test_focus_failure_releases_controls_without_reporting_confirmed_off(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror') as error:
            root=tk.Tk();root.withdraw();app=App(root)
            try:
                from unittest.mock import Mock
                app.robot=Mock(fault=True);app.robot.focus_laser.side_effect=RuntimeError('USB error')
                app.tool_mode.set('Laser');app.tool_changed();app.laser_safe.set(True);app.focus_laser()
                deadline=time.monotonic()+3
                while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                self.assertFalse(app.busy);self.assertFalse(app.focus_active)
                self.assertFalse(app.laser_safe.get());self.assertIsNone(app.robot)
                self.assertIn('Eroare',app.focus_status.get());self.assertTrue(error.called)
            finally:app.close()

    def test_shutdown_reports_unconfirmed_stop_and_still_releases_window(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror') as error:
            from unittest.mock import Mock
            root=tk.Tk();root.withdraw();app=App(root)
            app.robot=Mock(fault=True);app.robot.close.side_effect=RuntimeError('USB lost')
            app.close()
            self.assertIsNone(app.robot)
            self.assertIn('Întrerupe fizic',error.call_args.args[1])
            with self.assertRaises(tk.TclError):root.winfo_exists()

    def test_next_portrait_finishes_while_frozen_robot_job_keeps_running(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror') as error:
            root=tk.Tk();root.withdraw();app=App(root)
            gate=threading.Event();entered=threading.Event()
            try:
                model=Kinematics(test_core.KinematicTests().samples())
                samples=[p+[0]+model.inverse(p+[0]) for p in [[190,-40,0],[270,-40,0],[270,40,0],[190,40,0]]]
                class WaitingRobot(FakeRobot):
                    def continuous(self,points,cancel,progress):
                        entered.set();gate.wait(5)
                        super().continuous(points,cancel,progress)
                app.samples=samples;app.cal=Calibration([p[:3] for p in samples]);app.robot=WaitingRobot(model)
                app.file=str(ROOT/'examples/patrat.svg');app.fingerprint=app.current_fingerprint={'tool':b'tool'.hex()}
                app.clear.set(True);app.fixed.set(True);app.run(False)
                self.assertTrue(entered.wait(3));self.assertTrue(app.busy)
                self.assertTrue(app.studio.drawing_running)
                frozen=app.studio.active_drawing.tobytes()
                active_name=app.active_job.get()
                next_svg=ROOT/'examples/portrete/01_femeie_lineart.svg'
                photo=Image.new('RGB',(40,40),'white');app.studio.photo=photo
                app.invalidate_photo_result()
                with patch('dobot_draw.app.local_mode',return_value=True),patch('dobot_draw.app.save_capture',return_value=Path(temp)/'p.png'),patch('dobot_draw.local_ai.generate',return_value=next_svg):
                    app.generate_captured(photo)
                    deadline=time.monotonic()+3
                    while app.ai_busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                self.assertFalse(app.ai_busy);self.assertTrue(app.busy)
                self.assertEqual(app.active_job.get(),active_name)
                self.assertEqual(app.file,str(next_svg));self.assertEqual(app.studio.state,'result')
                self.assertEqual(app.studio.active_drawing.tobytes(),frozen)
                app.settings['offset'].set('20')
                gate.set();deadline=time.monotonic()+5
                while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                self.assertFalse(app.busy);self.assertFalse(error.called)
                self.assertFalse(app.studio.drawing_running)
                self.assertEqual(app.studio.active_drawing.tobytes(),frozen)
                self.assertTrue(app.robot.moves);self.assertLessEqual(max(p[2] for p in app.robot.moves),3)
                self.assertEqual(len(list(Path(temp).glob('job-*.json'))),1)
            finally:
                gate.set();app.close()

    def test_stop_robot_and_cancel_ai_are_independent(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)):
            root=tk.Tk();root.withdraw();app=App(root)
            try:
                app.busy=True;app.ai_busy=True
                app.stop();self.assertTrue(app.cancel.is_set());self.assertFalse(app.ai_cancel.is_set())
                app.cancel.clear();app.cancel_ai()
                self.assertTrue(app.ai_cancel.is_set());self.assertFalse(app.cancel.is_set())
            finally:app.busy=False;app.ai_busy=False;app.close()

    def test_new_photo_generation_survives_laser_finish_stop_and_error(self):
        for ending in ('finished','stopped','error'):
            with self.subTest(ending=ending),tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror'):
                gc.collect()
                root=tk.Tk();root.withdraw();app=App(root)
                robot_gate=threading.Event();robot_entered=threading.Event();ai_gate=threading.Event();ai_entered=threading.Event()
                try:
                    model=Kinematics(test_core.KinematicTests().samples())
                    samples=[p+[0]+model.inverse(p+[0]) for p in [[190,-40,0],[270,-40,0],[270,40,0],[190,40,0]]]
                    class LaserRobot(FakeRobot):
                        def prepare_laser(self):pass
                        def continuous(self,points,cancel,progress):
                            robot_entered.set();robot_gate.wait(5)
                            if ending=='error':raise RuntimeError('Simulated robot failure')
                            if cancel.is_set():raise RuntimeError('Stopped by user')
                            super().continuous(points,cancel,progress)
                        def continuous_laser(self,points,power,cancel,progress):self.continuous(points,cancel,progress)
                    app.robot=LaserRobot(model);app.samples=samples;app.cal=Calibration([p[:3] for p in samples])
                    app.fingerprint=app.current_fingerprint={'tool':b'tool'.hex()}
                    app.file=str(ROOT/'examples/patrat.svg');app.fixed.set(True);app.clear.set(True)
                    app.tool_mode.set('Laser');app.tool_changed();app.laser_z.set('5');app.laser_safe.set(True)
                    app.run(False);self.assertTrue(robot_entered.wait(2))
                    next_svg=ROOT/'examples/portrete/01_femeie_lineart.svg'
                    photo=Image.new('RGB',(40,40),'blue')
                    app.studio.result=Image.new('RGB',(40,40),'red')
                    def generate(source,dest,cancel,status,**kwargs):
                        ai_entered.set();ai_gate.wait(5)
                        self.assertFalse(cancel.is_set())
                        return next_svg
                    with patch('dobot_draw.app.local_mode',return_value=True),patch('dobot_draw.app.save_capture',return_value=Path(temp)/'new-photo.png'),patch('dobot_draw.local_ai.generate',side_effect=generate):
                        app.generate_captured(photo);self.assertTrue(ai_entered.wait(2))
                        self.assertIsNone(app.file);self.assertIsNone(app.studio.result)
                        if ending=='stopped':app.stop()
                        robot_gate.set();deadline=time.monotonic()+3
                        while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                        self.assertFalse(app.busy);self.assertTrue(app.ai_busy)
                        self.assertFalse(app.ai_cancel.is_set());self.assertEqual(app.studio.state,'generating')
                        app.preview();app.run(False)
                        self.assertIsNone(app.file);self.assertEqual(app.studio.state,'generating')
                        moves=len(app.robot.moves)
                        ai_gate.set();deadline=time.monotonic()+3
                        while app.ai_busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                        self.assertFalse(app.ai_busy);self.assertEqual(app.file,str(next_svg))
                        self.assertEqual(app.studio.state,'result');self.assertEqual(app.studio.photo.getpixel((0,0)),(0,0,255))
                        self.assertIsNotNone(app.studio.result);self.assertEqual(len(app.robot.moves),moves)
                        self.assertIn('completed',(Path(temp)/'ai-events.jsonl').read_text())
                finally:
                    robot_gate.set();ai_gate.set();app.close();app=None;root=None

    def test_ai_failure_does_not_unlock_or_cancel_robot(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror'):
            root=tk.Tk();root.withdraw();app=App(root)
            try:
                app.busy=True;app.ai_busy=True
                app.events.put(('ai_error','ComfyUI indisponibil','test traceback'))
                root.after_cancel(app.poll_id);app.poll()
                self.assertTrue(app.busy);self.assertFalse(app.ai_busy);self.assertFalse(app.cancel.is_set())
                self.assertIn('indisponibil',app.ai_status.get())
            finally:app.busy=False;app.close()

    def test_laser_probe_does_not_emit_and_engraving_uses_separate_z(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror') as error:
            root=tk.Tk();root.withdraw();app=App(root)
            try:
                model=Kinematics(test_core.KinematicTests().samples())
                samples=[p+[0]+model.inverse(p+[0]) for p in [[190,-40,0],[270,-40,0],[270,40,0],[190,40,0]]]
                class LaserRobot(FakeRobot):
                    strokes=[]
                    def prepare_laser(self):pass
                    def continuous_laser(self,points,power,cancel,progress):
                        self.strokes.append((points,power));self.continuous(points,cancel,progress)
                app.samples=samples;app.cal=Calibration([p[:3] for p in samples]);app.robot=LaserRobot(model)
                app.file=str(ROOT/'examples/patrat.svg');app.fingerprint=app.current_fingerprint={'tool':b'tool'.hex()}
                app.clear.set(True);app.fixed.set(True);app.tool_mode.set('Laser');app.tool_changed();app.laser_z.set('5')
                def wait():
                    deadline=time.monotonic()+5
                    while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    self.assertFalse(app.busy)
                app.run(True);wait();self.assertFalse(app.robot.strokes)
                self.assertFalse(error.called)
                app.laser_safe.set(True);app.run(False);wait();self.assertTrue(app.robot.strokes)
                self.assertTrue(all(p[2]==5 for points,_ in app.robot.strokes for p in points))
                self.assertEqual(app.cal.contact_z,0);self.assertFalse(error.called)
            finally:app.close()

    def test_linux_local_photo_never_requests_ssh_password(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.local_mode',return_value=True):
            root=tk.Tk();root.withdraw();app=App(root)
            try:
                photo=Image.new('RGB',(40,40),'white');app.studio.photo=photo
                with patch('dobot_draw.app.save_capture',return_value=Path(temp)/'photo.png'),patch('dobot_draw.app.simpledialog.askstring') as password,patch('dobot_draw.local_ai.generate',return_value=ROOT/'examples/patrat.svg') as generate:
                    app.generate_captured(photo)
                    deadline=time.monotonic()+5
                    while app.ai_busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    self.assertFalse(app.ai_busy);generate.assert_called_once();password.assert_not_called()
                    self.assertNotIn('people',generate.call_args.kwargs)
                    self.assertEqual(app.studio.state,'result');self.assertIsNone(app.robot)
            finally:app.close()

    def test_saved_photo_generates_preview_with_logo_without_starting_robot(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror') as error:
            root=tk.Tk();root.withdraw()
            try:
                app=App(root)
                photo=Image.new('RGB',(40,40),'white');app.studio.photo=photo;app.studio.state='captured'
                svg=ROOT/'examples/portrete/01_femeie_lineart.svg'
                with patch('dobot_draw.app.local_mode',return_value=False),patch('dobot_draw.app.save_capture',return_value=Path(temp)/'photo.png') as save,patch('dobot_draw.app.simpledialog.askstring',return_value='test'),patch('dobot_draw.gb10.generate',return_value=svg) as generate:
                    app.generate_captured(photo)
                    deadline=time.monotonic()+5
                    while app.ai_busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    self.assertFalse(app.ai_busy);self.assertFalse(error.called)
                    self.assertTrue(save.called);self.assertTrue(generate.called)
                    self.assertEqual(app.studio.state,'result')
                    self.assertEqual(app.studio.photo.tobytes(),photo.tobytes())
                    self.assertIsNotNone(app.studio.result)
                    self.assertIsNone(app.robot);self.assertIsNone(app.cal)
                    self.assertTrue(app.paths)
                    app.run(False);self.assertTrue(error.called)
            finally:app.close()

    def test_dry_then_draw_and_one_job_at_a_time(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.messagebox.showerror') as dialog:
            root=tk.Tk();root.withdraw()
            try:
                app=App(root)
                model=Kinematics(test_core.KinematicTests().samples())
                samples=[]
                for xyz in [[190,-40,0],[270,-40,0],[270,40,0],[190,40,0]]:
                    p=xyz+[0];samples.append(p+model.inverse(p))
                app.samples=samples;app.cal=Calibration([p[:3] for p in samples])
                app.robot=FakeRobot(model);app.file=str(ROOT/'examples/patrat.svg')
                app.fingerprint=app.current_fingerprint={'tool':b'tool'.hex()}
                app.clear.set(True);app.fixed.set(True)
                def wait():
                    deadline=time.monotonic()+5
                    while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    self.assertFalse(app.busy)
                app.run(False);wait()
                self.assertTrue(any(p[2]==0 for p in app.robot.moves))
                self.assertFalse(dialog.called)
                app.robot.moves=[]
                app.run(True);app.run(False);wait()
                self.assertTrue(app.dry_key);self.assertFalse(dialog.called)
                self.assertTrue(all(p[2]>0 for p in app.robot.moves))
                app.robot.moves=[]
                app.settings['speed'].set('150')
                app.settings['offset'].set('-0.5')
                app.run(False);wait()
                self.assertFalse(dialog.called)
                self.assertTrue(any(p[2]==-.5 for p in app.robot.moves))
                self.assertEqual(app.robot.current,[230.0,0.0,3.0,0.0])
                self.assertEqual(app.robot.stops,3)
                self.assertEqual(len(list(Path(temp).glob('job-*.json'))),3)
            finally:app.close()


if __name__=='__main__':unittest.main()
