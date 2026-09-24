"""Simulated integration: real planner/importer/UI worker, no hardware port."""
import tempfile
import time
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
    def test_linux_local_photo_never_requests_ssh_password(self):
        with tempfile.TemporaryDirectory() as temp,patch('dobot_draw.app.DATA',Path(temp)),patch('dobot_draw.app.local_mode',return_value=True):
            root=tk.Tk();root.withdraw();app=App(root)
            try:
                photo=Image.new('RGB',(40,40),'white');app.studio.photo=photo
                with patch('dobot_draw.app.save_capture',return_value=Path(temp)/'photo.png'),patch('dobot_draw.app.simpledialog.askstring') as password,patch('dobot_draw.local_ai.generate',return_value=ROOT/'examples/patrat.svg') as generate:
                    app.generate_captured(photo)
                    deadline=time.monotonic()+5
                    while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    self.assertFalse(app.busy);generate.assert_called_once();password.assert_not_called()
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
                    while app.busy and time.monotonic()<deadline:root.update();time.sleep(.01)
                    self.assertFalse(app.busy);self.assertFalse(error.called)
                    self.assertTrue(save.called);self.assertTrue(generate.called)
                    self.assertEqual(app.studio.state,'result')
                    self.assertIs(app.studio.photo,photo)
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
