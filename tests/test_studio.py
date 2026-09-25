import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from dobot_draw.studio import Camera,Studio,center_square,save_capture,render_paths,camera_modes,configure_camera


class FakeCamera:
    def __init__(self,index):
        self.error=None;self.image=Image.new('RGB',(40,40),'red');self.closed=False
        self.thread=type('Thread',(),{'is_alive':lambda _:False})()
        self.requested=False;self.captured=None
    def snapshot(self):return self.image,100
    def close(self):self.closed=True
    def request_capture(self):self.requested=True
    def capture_result(self):return self.captured


class StudioTests(unittest.TestCase):
    def test_linux_camera_uses_largest_advertised_mode(self):
        listing="""[0]: 'YUYV' (YUYV 4:2:2)\n    Size: Discrete 640x480\n[1]: 'MJPG' (Motion-JPEG)\n    Size: Discrete 1920x1080\n    Size: Discrete 3840x2160\n"""
        result=type('Result',(),{'returncode':0,'stdout':listing})()
        with patch('dobot_draw.studio.sys.platform','linux'),patch('dobot_draw.studio.subprocess.run',return_value=result):
            self.assertEqual(camera_modes(2)[0],(3840,2160,'MJPG',0))

    def test_camera_configuration_sets_native_mode_without_square_resize(self):
        cap=type('Cap',(),{'values':{},'set':lambda self,key,value:self.values.__setitem__(key,value) or True,
                          'get':lambda self,key:{3:3840,4:2160}[key]})()
        cv2=type('CV',(),{'CAP_PROP_FOURCC':6,'CAP_PROP_FRAME_WIDTH':3,'CAP_PROP_FRAME_HEIGHT':4,
                          'CAP_PROP_FPS':5,'CAP_PROP_BUFFERSIZE':38,
                          'VideoWriter_fourcc':staticmethod(lambda *value:123)})
        with patch('dobot_draw.studio.camera_modes',return_value=[(3840,2160,'MJPG',30)]):
            self.assertEqual(configure_camera(cap,cv2,0),(3840,2160))
        self.assertEqual(cap.values[3],3840);self.assertEqual(cap.values[4],2160)
        self.assertEqual(cap.values[5],30);self.assertEqual(cap.values[38],1)

    def test_camera_preview_selects_fast_native_mode_but_photo_uses_maximum(self):
        listing="""[0]: 'YUYV'\n Size: Discrete 2304x1536\n Interval: Discrete 0.500s (2.000 fps)\n[1]: 'MJPG'\n Size: Discrete 1920x1080\n Interval: Discrete 0.033s (30.000 fps)\n Interval: Discrete 0.200s (5.000 fps)\n"""
        from unittest.mock import Mock
        import cv2
        with patch('dobot_draw.studio.sys.platform','linux'),patch('dobot_draw.studio.subprocess.run',return_value=Mock(returncode=0,stdout=listing)):
            modes=camera_modes(0)
        self.assertEqual(modes,[(2304,1536,'YUYV',2),(1920,1080,'MJPG',30)])
        cap=Mock();values={}
        cap.set.side_effect=lambda key,value:values.__setitem__(key,value) or True
        cap.get.side_effect=lambda key:values[key]
        self.assertEqual(configure_camera(cap,cv2,0,purpose='preview',modes=modes),(1920,1080))
        self.assertEqual(values[cv2.CAP_PROP_FPS],30)
        self.assertEqual(configure_camera(cap,cv2,0,modes=modes),(2304,1536))
        self.assertEqual(values[cv2.CAP_PROP_FPS],2)

    def test_capture_saves_fresh_maximum_frame_not_cached_preview(self):
        import threading
        import numpy as np
        from unittest.mock import Mock
        camera=Camera.__new__(Camera)
        camera.stop=threading.Event();camera.lock=threading.Lock();camera.capture_requested=threading.Event()
        camera.captured=None;camera.error=None;camera.request_capture()
        cap=Mock();cap.read.side_effect=[(True,np.full((3,5,3),11,dtype=np.uint8)),(True,np.full((3,5,3),77,dtype=np.uint8))]
        with patch('cv2.VideoCapture',return_value=cap),patch('dobot_draw.studio.camera_modes',return_value=[]),patch('dobot_draw.studio.configure_camera',side_effect=[(1920,1080),(5,3)]):
            camera._read(0)
        self.assertIsNone(camera.error);self.assertEqual(camera.captured.size,(3,3))
        self.assertEqual(camera.captured.getpixel((1,1)),(77,77,77));cap.release.assert_called_once()

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
            self.assertEqual(studio.state,'capturing');self.assertTrue(camera.requested)
            self.assertFalse(camera.closed);self.assertEqual(saved,[])
            camera.captured=Image.new('RGB',(80,80),'red')
            with patch('dobot_draw.studio.time.monotonic',return_value=105.5):studio.tick()
            self.assertEqual(studio.state,'captured');self.assertTrue(camera.closed)
            self.assertEqual(studio.photo.size,(80,80))
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

    def test_live_preview_skips_unchanged_frames_and_capture_timeout_is_visible(self):
        root=tk.Tk();root.withdraw();errors=[];studio=Studio(root,lambda _:None,lambda:None,errors.append)
        try:
            with patch('dobot_draw.studio.Camera',FakeCamera),patch('dobot_draw.studio.time.monotonic',return_value=100):
                studio.live()
                with patch.object(studio,'paint') as paint:
                    studio.tick();studio.tick();self.assertEqual(paint.call_count,1)
                studio.start_timer()
            studio.camera.snapshot=lambda:(studio.camera.image,105)
            with patch('dobot_draw.studio.time.monotonic',return_value=105):studio.tick()
            self.assertEqual(studio.state,'capturing')
            with patch('dobot_draw.studio.time.monotonic',return_value=114):studio.tick()
            self.assertEqual(studio.state,'empty');self.assertIsNone(studio.photo)
            self.assertIn('rezoluția maximă',errors[0])
        finally:studio.close();root.destroy()


if __name__=='__main__':unittest.main()
