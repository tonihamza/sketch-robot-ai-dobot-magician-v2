import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from dobot_draw.studio import Studio,center_square,save_capture,render_paths


class FakeCamera:
    def __init__(self,index):
        self.error=None;self.image=Image.new('RGB',(40,40),'red');self.closed=False
        self.thread=type('Thread',(),{'is_alive':lambda _:False})()
    def snapshot(self):return self.image,100
    def close(self):self.closed=True


class StudioTests(unittest.TestCase):
    def test_centre_crop_is_exact_and_does_not_modify_input(self):
        image=Image.new('RGB',(8,4),'red')
        for x in range(2,6):
            for y in range(4):image.putpixel((x,y),(0,255,0))
        square=center_square(image)
        self.assertEqual(square.size,(4,4));self.assertEqual(square.getpixel((0,0)),(0,255,0))
        self.assertEqual(image.size,(8,4));self.assertEqual(image.getpixel((0,0)),(255,0,0))

    def test_save_is_unique_square_and_renderer_uses_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Image.new('RGB',(9,5),'white')
            a=save_capture(image,folder);b=save_capture(image,folder)
            self.assertNotEqual(a,b)
            with Image.open(a) as saved:self.assertEqual(saved.size,(5,5))
        rendered=render_paths([[(10,10),(20,10)]],80,80,800)
        self.assertNotEqual(rendered.getpixel((150,100)),(255,255,255))

    def test_countdown_capture_requires_save_and_retake_releases_camera(self):
        root=tk.Tk();root.withdraw();saved=[];errors=[]
        studio=Studio(root,saved.append,lambda:None,errors.append)
        try:
            with patch('dobot_draw.studio.Camera',FakeCamera),patch('dobot_draw.studio.time.monotonic',return_value=100):
                studio.live();camera=studio.camera;studio.start_timer()
                self.assertEqual(studio.deadline,105)
                self.assertEqual(saved,[])
            camera.snapshot=lambda:(camera.image,105)
            with patch('dobot_draw.studio.time.monotonic',return_value=105):studio.tick()
            self.assertEqual(studio.state,'captured');self.assertTrue(camera.closed)
            self.assertEqual(saved,[])
            studio.save();self.assertEqual(len(saved),1)
            self.assertEqual(errors,[])
            with patch('dobot_draw.studio.Camera',FakeCamera):studio.live()
            self.assertIsNone(studio.result)
            camera=studio.camera;studio.hide();self.assertTrue(camera.closed)
            self.assertIsNone(studio.deadline)
        finally:studio.close();root.destroy()

    def test_stale_camera_frame_is_not_captured(self):
        root=tk.Tk();root.withdraw();errors=[];studio=Studio(root,lambda _:None,lambda:None,errors.append)
        try:
            with patch('dobot_draw.studio.Camera',FakeCamera),patch('dobot_draw.studio.time.monotonic',return_value=100):
                studio.live();studio.start_timer()
            with patch('dobot_draw.studio.time.monotonic',return_value=105):studio.tick()
            self.assertEqual(studio.state,'empty');self.assertTrue(errors)
        finally:studio.close();root.destroy()


if __name__=='__main__':unittest.main()
