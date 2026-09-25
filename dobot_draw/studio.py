"""Camera preview and capture workflow; no robot commands."""
import math
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageOps, ImageTk, ImageDraw


def center_square(image):
    image=ImageOps.exif_transpose(image).convert('RGB')
    w,h=image.size;n=min(w,h)
    return image.crop(((w-n)//2,(h-n)//2,(w-n)//2+n,(h-n)//2+n))


def camera_modes(index):
    """Return V4L2 discrete modes, largest first; empty means probe via OpenCV."""
    if not sys.platform.startswith('linux'):
        return []
    device=index if isinstance(index,str) and index.startswith('/dev/') else f'/dev/video{index}'
    try:
        result=subprocess.run(['v4l2-ctl','--device',device,'--list-formats-ext'],
                              capture_output=True,text=True,timeout=5)
    except (OSError,subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    pixel=None;modes=[]
    for line in result.stdout.splitlines():
        found=re.search(r"'([^']+)'",line)
        if found and ('Pixel Format' in line or re.search(r'^\s*\[\d+\]:',line)):
            pixel=found.group(1)
        size=re.search(r'Size:\s+Discrete\s+(\d+)x(\d+)',line)
        if size and pixel:
            width,height=map(int,size.groups())
            modes.append((width,height,pixel,0.0))
        rate=re.search(r'\(([\d.]+) fps\)',line)
        if rate and modes:
            modes[-1]=(*modes[-1][:3],max(modes[-1][3],float(rate.group(1))))
    # At equal resolution MJPG generally permits a better frame rate than raw YUYV.
    priority={'MJPG':2,'JPEG':2,'YUYV':1}
    return sorted(set(modes),key=lambda mode:(mode[0]*mode[1],priority.get(mode[2],0),mode[3]),reverse=True)


def configure_camera(cap,cv2,index,*,purpose='photo',modes=None):
    """Full sensor frames: fast native video for preview, maximum for capture."""
    if modes is None:modes=camera_modes(index)
    requested=None
    if modes:
        candidates=[mode for mode in modes if mode[3]>=20] if purpose=='preview' else modes
        mode=(candidates or modes)[0]
        width,height,pixel,fps=mode
        requested=(width,height)
        if len(pixel)==4:
            cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*pixel))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT,height)
        if fps:cap.set(cv2.CAP_PROP_FPS,fps)
    else:
        # V4L2 clamps an oversized TRY_FMT request to the largest supported mode.
        # This also provides a useful fallback when v4l2-ctl is unavailable.
        if sys.platform.startswith('linux'):
            cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,16384)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT,16384)
        else:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT,1080)
    # Avoid a backlog of old frames, especially in a native 2 fps still mode.
    cap.set(cv2.CAP_PROP_BUFFERSIZE,1)
    width=round(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width<=0 or height<=0:
        raise RuntimeError('Camera nu a confirmat rezoluția video.')
    if requested and (width,height)!=requested:
        raise RuntimeError(f'Camera nu a acceptat rezoluția {requested[0]}×{requested[1]} (a raportat {width}×{height}).')
    return width,height


def render_paths(paths,width,height,size=900):
    image=Image.new('RGB',(size,size),'white');draw=ImageDraw.Draw(image)
    for path in paths:
        if len(path)>1:draw.line([(x/width*size,y/height*size) for x,y in path],fill='#152f43',width=2)
    return image


class Camera:
    def __init__(self,index):
        self.stop=threading.Event();self.lock=threading.Lock()
        self.image=None;self.stamp=0;self.error=None
        self.capture_requested=threading.Event();self.captured=None
        self.preview_size=None;self.capture_size=None;self.frames=0;self.started_at=None
        self.thread=threading.Thread(target=self._read,args=(index,),daemon=True);self.thread.start()

    def _read(self,index):
        cap=None
        try:
            import cv2
            # On the GB10 OpenCV discovers V4L2 correctly through CAP_ANY,
            # while forcing CAP_V4L2 can fail when PipeWire also monitors UVC.
            backend=cv2.CAP_DSHOW if sys.platform=='win32' else cv2.CAP_ANY
            cap=cv2.VideoCapture(index,backend)
            if not cap.isOpened():raise RuntimeError('Camera nu se poate deschide. Verifică indexul și dacă este ocupată.')
            modes=camera_modes(index)
            self.preview_size=configure_camera(cap,cv2,index,purpose='preview',modes=modes)
            failures=0
            while not self.stop.is_set():
                if self.capture_requested.is_set():
                    self.capture_size=configure_camera(cap,cv2,index,modes=modes)
                    # Reconfiguration restarts the stream. Discard one frame;
                    # never save the old preview as a maximum-resolution photo.
                    cap.read()
                    ok,frame=cap.read()
                    if self.stop.is_set():return
                    if not ok or (frame.shape[1],frame.shape[0])!=self.capture_size:
                        raise RuntimeError('Camera nu a livrat fotografia la rezoluția de captură.')
                    image=center_square(Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)))
                    with self.lock:self.captured=image
                    return
                ok,frame=cap.read()
                if not ok:
                    failures+=1
                    if failures>15:raise RuntimeError('Camera nu mai transmite imagini.')
                    self.stop.wait(.05);continue
                failures=0
                # Keep the full native frame from the camera and crop only its
                # central square. No stretch/downscale is applied before saving.
                image=center_square(Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)))
                with self.lock:
                    self.image=image;self.stamp=time.monotonic();self.frames+=1
                    if self.started_at is None:self.started_at=self.stamp
        except Exception as exc:self.error=str(exc)
        finally:
            if cap is not None:cap.release()

    def snapshot(self):
        with self.lock:return self.image,self.stamp

    def request_capture(self):self.capture_requested.set()

    def capture_result(self):
        with self.lock:return self.captured

    def close(self):self.stop.set()


class Studio:
    def __init__(self,root,on_save,on_new,on_error):
        self.root=root;self.on_save=on_save;self.on_new=on_new;self.on_error=on_error
        self.camera=None;self.retired=[];self.photo=None;self.result=None
        self.state='empty';self.deadline=None;self.dialog=None;self.closed=False
        self.last_frame_stamp=None;self.last_countdown=None;self.capture_deadline=None
        self.active_drawing=None;self.drawing_running=False;self.drawing_action=''
        self.drawing_percent=0;self.drawing_photo=None
        self.window=tk.Toplevel(root);self.window.title('LAPTOP AID · Cameră și portret')
        self.window.geometry('1000x640');self.window.minsize(420,350)
        self.window.protocol('WM_DELETE_WINDOW',self.hide)
        self.message=tk.StringVar(value='Alege o fotografie, pornește camera sau încarcă un SVG din fereastra principală.')
        header=ttk.Frame(self.window);header.pack(fill='x')
        self.drawing_card=ttk.Frame(header,padding=8)
        self.drawing_caption=tk.StringVar(value='')
        ttk.Label(self.drawing_card,textvariable=self.drawing_caption,wraplength=155).pack()
        self.drawing_canvas=tk.Canvas(self.drawing_card,width=150,height=150,bg='white',highlightthickness=1,highlightbackground='#64748b')
        self.drawing_canvas.pack()
        self.message_label=ttk.Label(header,textvariable=self.message,wraplength=650,padding=10)
        self.message_label.pack(side='left',fill='both',expand=True)
        header.bind('<Configure>',lambda e:self.message_label.configure(wraplength=max(150,e.width-(190 if self.active_drawing is not None else 20))))
        self.canvas=tk.Canvas(self.window,bg='#16212b',highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda _:self.paint())
        self.photos=[];self.tick_id=root.after(40,self.tick)

    def show(self):self.window.deiconify();self.window.lift()

    def set_active_drawing(self,image,action):
        # This snapshot belongs to the robot job, independently of the next
        # photograph/result. Never replace it in capture or AI callbacks.
        self.active_drawing=image.copy();self.drawing_action=action
        self.drawing_running=True;self.drawing_percent=0
        self.drawing_caption.set(f'{action} · pregătire')
        self.drawing_card.pack(side='right',anchor='ne',before=self.message_label)
        self.drawing_photo=ImageTk.PhotoImage(self.active_drawing.resize((150,150),Image.Resampling.LANCZOS),master=self.window)
        self.drawing_canvas.delete('all');self.drawing_canvas.create_image(75,75,image=self.drawing_photo)
        self.show()

    def update_drawing_progress(self,percent):
        if not self.drawing_running:return
        percent=max(0,min(100,int(percent)))
        if percent!=self.drawing_percent:
            self.drawing_percent=percent
            self.drawing_caption.set(f'{self.drawing_action} în curs · {percent}%')

    def finish_drawing(self,success):
        if not self.drawing_running:return
        self.drawing_running=False
        if success:self.drawing_percent=100
        status='terminată' if success else 'oprită'
        self.drawing_caption.set(f'{self.drawing_action} {status} · {self.drawing_percent}%')

    def stop_camera(self):
        if self.camera:
            self.camera.close();self.retired.append(self.camera);self.camera=None
        self.deadline=None
        self.capture_deadline=None

    def clear_dialog(self):
        if self.dialog and self.dialog.winfo_exists():self.dialog.destroy()
        self.dialog=None

    def panel(self,title,buttons):
        self.clear_dialog();self.dialog=tk.Toplevel(self.root);self.dialog.title(title)
        self.dialog.transient(self.window);self.dialog.resizable(False,False)
        ttk.Label(self.dialog,text=title,padding=15,font=('Segoe UI',13,'bold')).pack()
        row=ttk.Frame(self.dialog,padding=12);row.pack()
        for label,action in buttons:ttk.Button(row,text=label,command=action).pack(side='left',padx=6)
        self.dialog.protocol('WM_DELETE_WINDOW',self.cancel_capture)
        self.dialog.update_idletasks()
        self.dialog.geometry(f'+{self.root.winfo_rootx()+160}+{self.root.winfo_rooty()+180}')

    def live(self,index=0):
        self.stop_camera()
        self.retired=[c for c in self.retired if c.thread.is_alive()]
        if self.retired:
            self.on_error('Camera se închide; încearcă din nou peste o secundă.');return
        self.photo=None;self.result=None;self.state='live';self.camera=Camera(index)
        self.last_frame_stamp=None;self.last_countdown=None
        self.message.set('Camera · previzualizare fluidă · fotografia se salvează la rezoluția maximă, cu decupaj pătrat central');self.show()
        self.panel('Pregătit pentru fotografie?', [('Pornește timerul · 5 secunde',self.start_timer),('Anulează',self.cancel_capture)])

    def start_timer(self):
        if self.state!='live' or not self.camera:return
        image,stamp=self.camera.snapshot()
        if image is None or time.monotonic()-stamp>1:
            self.on_error('Așteaptă până apare imaginea live a camerei.');return
        self.deadline=time.monotonic()+5;self.state='countdown';self.clear_dialog();self.show()

    def tick(self):
        if self.closed:return
        self.root.after_cancel(self.tick_id)
        if self.camera:
            if self.camera.error:
                error=self.camera.error;self.cancel_capture();self.message.set(error);self.on_error(error)
            else:
                image,stamp=self.camera.snapshot()
                changed=stamp!=self.last_frame_stamp
                if image is not None and changed:self.photo=image;self.last_frame_stamp=stamp
                if self.deadline and time.monotonic()>=self.deadline:
                    if image is None or time.monotonic()-stamp>1:
                        self.cancel_capture();self.on_error('Fotografia nu a fost făcută: camera nu mai transmite.')
                    else:
                        self.deadline=None;self.state='capturing';self.capture_deadline=time.monotonic()+8
                        self.camera.request_capture()
                        self.message.set('Captură la rezoluția maximă…');self.paint()
                if self.state=='capturing' and self.camera:
                    captured=self.camera.capture_result()
                    if captured is not None:
                        self.photo=captured;self.stop_camera();self.confirm()
                    elif time.monotonic()>=self.capture_deadline:
                        self.cancel_capture();self.on_error('Camera nu a livrat fotografia la rezoluția maximă în timp util. Reîncearcă.')
                countdown=math.ceil(self.deadline-time.monotonic()) if self.deadline else None
                if self.state in ('live','countdown') and (changed or countdown!=self.last_countdown):self.paint()
                self.last_countdown=countdown
        self.tick_id=self.root.after(40,self.tick)

    def selected(self,filename):
        with Image.open(filename) as image:photo=center_square(image)
        self.stop_camera();self.photo=photo;self.result=None;self.show();self.confirm()

    def confirm(self):
        self.state='captured';self.message.set('Verifică fotografia pătrată. Salvează pentru generare AI.');self.show();self.paint()
        self.panel('Păstrăm fotografia?', [('Salvează și generează',self.save),('Fă altă poză',self.on_new)])

    def save(self):
        if self.state!='captured' or self.photo is None:return
        self.clear_dialog()
        self.on_save(self.photo.copy())

    def generating(self):
        self.result=None;self.state='generating'
        self.message.set('Fotografie salvată · se generează portretul pe GB10…')
        self.paint()

    def set_result(self,image):
        self.stop_camera();self.clear_dialog();self.result=image;self.state='result'
        self.message.set('Original / portret pregătit pentru robot · apasă DESENEAZĂ / GRAVEAZĂ în fereastra principală.')
        self.show();self.paint()

    def cancel_capture(self):
        self.stop_camera();self.clear_dialog()
        self.state='empty';self.photo=None;self.result=None;self.message.set('Captură anulată.');self.paint()

    def hide(self):
        if self.state in ('live','countdown','capturing'):self.cancel_capture()
        self.window.withdraw()

    def paint(self):
        c=self.canvas;c.delete('all');self.photos=[]
        w,h=max(1,c.winfo_width()),max(1,c.winfo_height())
        images=[(self.photo,'Fotografie')]
        if self.result is not None:images.append((self.result,'Portret + logo'))
        if self.photo is None and self.result is not None:images=[(self.result,'Desen pregătit')]
        size=max(1,int(min(w/len(images)-30,h-55)))
        for i,(img,label) in enumerate(images):
            cx=(i+.5)*w/len(images);cy=h/2+10
            c.create_text(cx,18,text=label,fill='white',font=('Segoe UI',13))
            if img is not None:
                resample=Image.Resampling.BILINEAR if self.state in ('live','countdown','capturing') else Image.Resampling.LANCZOS
                display=ImageTk.PhotoImage(img.resize((size,size),resample),master=self.window)
                self.photos.append(display);c.create_image(cx,cy,image=display)
            else:c.create_text(cx,cy,text='Camera / fotografia va apărea aici',fill='#b9c8d4')
        if self.deadline:
            value=max(0,math.ceil(self.deadline-time.monotonic()))
            font=('Segoe UI',max(35,int(size*.3)),'bold')
            c.create_text(w/2+3,h/2+3,text=str(value),fill='#15202b',font=font)
            c.create_text(w/2,h/2,text=str(value),fill='white',font=font)

    def close(self):
        if self.closed:return
        self.closed=True;self.stop_camera();self.clear_dialog()
        self.root.after_cancel(self.tick_id)
        self.window.destroy()


def save_capture(image,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'photo-{uuid.uuid4().hex}.png';center_square(image).save(path)
    return path
