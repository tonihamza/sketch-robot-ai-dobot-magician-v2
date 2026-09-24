import json
import math
import queue
import threading
import time
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from serial.tools import list_ports
from .robot import Robot, RobotError
from .geometry import Calibration, build_plan, build_laser_plan
from .kinematics import Kinematics
from .svg import load_svg
from .studio import Studio, save_capture, render_paths
from .local_ai import local_mode

ROOT=Path(__file__).resolve().parent.parent
DATA=ROOT/'data'
NAMES=['1 · STÂNGA SUS','2 · DREAPTA SUS','3 · DREAPTA JOS','4 · STÂNGA JOS']


class App:
    def __init__(self, root):
        self.root=root
        root.title('Dobot · Studio foto și SVG 80 × 80 mm — USB direct')
        root.geometry(f'1140x{min(940,root.winfo_screenheight()-100)}')
        root.minsize(1030,700)
        self.robot=None;self.busy=False;self.cal=None;self.samples=[];self.paths=[]
        self.file=None;self.fingerprint=None;self.dry_key=None;self.close_pending=False
        self.events=queue.Queue();self.cancel=threading.Event()
        self.ai_busy=False;self.ai_cancel=threading.Event()
        self.ai_status=tk.StringVar(value='AI liber · poți pregăti următorul portret în timpul desenării')
        self.active_job=tk.StringVar(value='Robot: nicio lucrare în execuție')
        self.tool_mode=tk.StringVar(value='Pix');self.selected_mode='Pix'
        self.laser_z=tk.StringVar(value='');self.laser_speed=tk.StringVar(value='5');self.laser_power=tk.StringVar(value='10')
        self.laser_safe=tk.BooleanVar(value=False)
        self.focus_active=False;self.disconnect_after_focus=False
        self.focus_status=tk.StringVar(value='Focalizare: neactivată')
        self.status=tk.StringVar(value='Deconectat · Conectează robotul pentru calibrare')
        devices=list(list_ports.comports())
        preferred=next((p.device for p in devices if p.vid==0x10c4 and p.pid==0xea60),None)
        self.port=tk.StringVar(value=preferred or ('/dev/ttyUSB0' if local_mode() else 'COM5'))
        self.settings={k:tk.StringVar(value=v) for k,v in [('margin','5'),('lift','3'),('offset','0'),('speed','100'),('z_speed','30'),('join_gap','0.3')]}
        self.ai_steps=tk.StringVar(value='24')
        self.brand=tk.BooleanVar(value=True)
        self.camera_index=tk.StringVar(value="0")
        self.studio=None
        self.preview_cal=None
        self.clear=tk.BooleanVar(value=False)
        self.fixed=tk.BooleanVar(value=False)
        style=ttk.Style();style.theme_use('clam')
        style.configure('TButton',padding=7)
        outer=ttk.Frame(root,padding=16);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='DOBOT  /  SVG PE HÂRTIE',font=('Segoe UI',20,'bold')).pack(anchor='w')
        ttk.Label(outer,text='USB direct • fără DobotLab / DobotLink • toate fișierele rămân locale').pack(anchor='w',pady=(2,12))
        top=ttk.Frame(outer);top.pack(fill='x')
        self.ports=ttk.Combobox(top,textvariable=self.port,width=19,values=[p.device for p in devices],postcommand=self.refresh_ports);self.ports.pack(side='left')
        self.connect_button=ttk.Button(top,text='Conectează USB',command=self.connect);self.connect_button.pack(side='left',padx=8)
        ttk.Button(top,text='Citește poziția',command=self.read_pose).pack(side='left')
        tk.Button(top,text='■  STOP',bg='#b42332',fg='white',font=('Segoe UI',12,'bold'),command=self.stop,padx=22).pack(side='right')
        body=ttk.Frame(outer);body.pack(fill='both',expand=True,pady=12)
        leftbox=ttk.Frame(body,width=445);leftbox.pack(side='left',fill='y',padx=(0,16));leftbox.pack_propagate(False)
        scroller=tk.Canvas(leftbox,highlightthickness=0,width=420)
        scrollbar=ttk.Scrollbar(leftbox,orient='vertical',command=scroller.yview);scrollbar.pack(side='right',fill='y')
        scroller.configure(yscrollcommand=scrollbar.set);scroller.pack(side='left',fill='both',expand=True)
        left=ttk.Frame(scroller);leftid=scroller.create_window((0,0),window=left,anchor='nw')
        left.bind('<Configure>',lambda _:scroller.configure(scrollregion=scroller.bbox('all')))
        scroller.bind('<Configure>',lambda e:scroller.itemconfigure(leftid,width=e.width))
        ttk.Label(left,text='1. Calibrează foaia',font=('Segoe UI',14,'bold')).pack(anchor='w')
        ttk.Label(left,text='Privind foaia din locul tău: SUS = marginea îndepărtată.\nCu Unlock, pune pixul pe foaie cu presiunea dorită în arc.\nEliberează Unlock și memorează colțurile în ordine.',wraplength=405).pack(anchor='w',pady=6)
        self.capture_button=ttk.Button(left,text='Memorează 1 · STÂNGA SUS',command=self.capture);self.capture_button.pack(fill='x')
        self.corner_labels=[]
        for name in NAMES:
            label=ttk.Label(left,text=name+'  —',font=('Consolas',10));label.pack(anchor='w',pady=3);self.corner_labels.append(label)
        row=ttk.Frame(left);row.pack(fill='x',pady=6)
        ttk.Button(row,text='Calibrare nouă',command=self.new_cal).pack(side='left')
        ttk.Button(row,text='Încarcă salvată',command=self.load_cal).pack(side='left',padx=6)
        self.cal_label=ttk.Label(left,text='Fără calibrare',wraplength=400);self.cal_label.pack(anchor='w')
        ttk.Checkbutton(left,text='Suportul, robotul și pixul sunt fixe ca la calibrare',variable=self.fixed).pack(anchor='w',pady=5)
        mode_row=ttk.Frame(left);mode_row.pack(fill='x',pady=4)
        ttk.Label(mode_row,text='Unealtă').pack(side='left')
        mode=ttk.Combobox(mode_row,textvariable=self.tool_mode,values=['Pix','Laser'],state='readonly',width=10)
        mode.pack(side='left',padx=8);mode.bind('<<ComboboxSelected>>',self.tool_changed)
        self.laser_frame=ttk.Frame(left)
        for i,(label,var) in enumerate([('Z laser absolut (mm)',self.laser_z),('Viteză laser (mm/s)',self.laser_speed),('Putere laser (%)',self.laser_power)]):
            ttk.Label(self.laser_frame,text=label).grid(row=i,column=0,sticky='w')
            ttk.Entry(self.laser_frame,textvariable=var,width=10).grid(row=i,column=1,padx=8)
        ttk.Button(self.laser_frame,text='Memorează Z laser (fascicul oprit)',command=self.capture_laser_z).grid(row=3,column=0,columnspan=2,sticky='ew')
        ttk.Label(self.laser_frame,text='JLM4035ZA-G1Y5 · Z la focalizare, fără contact.\nVerifică alinierea fasciculului cu zona XY a pixului.',wraplength=390).grid(row=4,column=0,columnspan=2,sticky='w')
        ttk.Checkbutton(self.laser_frame,text='XY aliniat; zonă protejată, ochelari\nși material verificate',variable=self.laser_safe).grid(row=5,column=0,columnspan=2,sticky='w')
        self.focus_button=ttk.Button(self.laser_frame,text='Aprinde laserul · 1 secundă',command=self.focus_laser)
        self.focus_button.grid(row=6,column=0,sticky='ew',pady=4)
        ttk.Button(self.laser_frame,text='STINGE / STOP',command=self.stop).grid(row=6,column=1,sticky='ew')
        ttk.Label(self.laser_frame,text='Probă ON/OFF: puterea (%) de gravare nu se aplică.\nPoate arde materialul. Reglează poziția cu laserul stins,\napoi verifică punctul și memorează Z. Fără mișcare automată.',wraplength=390).grid(row=7,column=0,columnspan=2,sticky='w')
        ttk.Label(self.laser_frame,textvariable=self.focus_status,wraplength=390).grid(row=8,column=0,columnspan=2,sticky='w')
        ttk.Label(left,text='2. Încarcă desenul',font=('Segoe UI',14,'bold')).pack(anchor='w',pady=(12,4))
        ttk.Button(left,text='Alege fișier SVG…',command=self.choose_svg).pack(fill='x')
        photorow=ttk.Frame(left);photorow.pack(fill='x',pady=3)
        ttk.Button(photorow,text='Alege fotografie…',command=self.generate_photo).pack(side='left')
        ttk.Button(photorow,text='Fotografie nouă',command=self.new_photo).pack(side='left',padx=4)
        camerow=ttk.Frame(left);camerow.pack(fill='x')
        ttk.Label(camerow,text='Cameră (index)').pack(side='left')
        ttk.Entry(camerow,textvariable=self.camera_index,width=4).pack(side='left',padx=5)
        ttk.Button(camerow,text='Arată fereastra foto',command=lambda:self.studio.show()).pack(side='left')
        airow=ttk.Frame(left);airow.pack(fill='x')
        ttk.Label(airow,text='Pași AI: 16 rapid / 24 echilibrat / 40 detaliat').pack(side='left')
        ttk.Combobox(airow,textvariable=self.ai_steps,values=['16','24','32','40'],width=7).pack(side='left',padx=10)
        ttk.Button(left,text='Anulează generarea AI',command=self.cancel_ai).pack(anchor='w')
        self.file_label=ttk.Label(left,text='Niciun SVG ales',wraplength=400);self.file_label.pack(anchor='w',pady=4)
        fields=ttk.Frame(left);fields.pack(fill='x')
        for i,(key,label) in enumerate([('margin','Margine / micșorare desen (mm)'),('lift','Ridicare pix (mm)'),('offset','Corecție Z: minus = mai jos (mm)'),('speed','Viteză desen (mm/s)'),('z_speed','Viteză Z (mm/s)'),('join_gap','Unire capete (mm; 0 = oprit)')]):
            ttk.Label(fields,text=label).grid(row=i,column=0,sticky='w',pady=3)
            ttk.Entry(fields,textvariable=self.settings[key],width=9).grid(row=i,column=1,padx=12)
        ttk.Button(left,text='Actualizează previzualizarea',command=self.preview).pack(fill='x',pady=6)
        def bind_scroll(widget):
            widget.bind('<MouseWheel>',lambda e:scroller.yview_scroll(-1 if e.delta>0 else 1,'units'),add='+')
            widget.bind('<Button-4>',lambda e:scroller.yview_scroll(-1,'units'),add='+')
            widget.bind('<Button-5>',lambda e:scroller.yview_scroll(1,'units'),add='+')
            for child in widget.winfo_children():bind_scroll(child)
        bind_scroll(left)
        right=ttk.Frame(body);right.pack(side='left',fill='both',expand=True)
        self.canvas=tk.Canvas(right,bg='#e9eef1',highlightthickness=0);self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',lambda e:self.paint())
        self.info=ttk.Label(right,text='Calibrează cele patru colțuri și alege un SVG.',wraplength=570);self.info.pack(fill='x',pady=6)
        ttk.Checkbutton(right,text='Logo LAPTOP AID în stânga sus',variable=self.brand,command=self.preview).pack(anchor='w')
        ttk.Label(right,text='3. Poziționează și pornește',font=('Segoe UI',14,'bold')).pack(anchor='w',pady=(9,4))
        self.position_help=ttk.Label(right,text='Cu Unlock, pune pixul DEASUPRA foii, în interiorul celor patru colțuri.\nÎntre linii: Z de desen + ridicarea setată. La final revine\nla poziția înaltă de pornire, pentru schimbarea foii.',wraplength=570)
        self.position_help.pack(anchor='w')
        ttk.Checkbutton(right,text='Pixul ȘI brațul au loc; suportul nu le blochează',variable=self.clear).pack(anchor='w',pady=5)
        runrow=ttk.Frame(right);runrow.pack(fill='x')
        self.probe_button=ttk.Button(runrow,text='Probă cu pixul ridicat',command=lambda:self.run(True));self.probe_button.pack(side='left')
        self.run_button=ttk.Button(runrow,text='DESENEAZĂ',command=lambda:self.run(False));self.run_button.pack(side='left',padx=8)
        ttk.Label(outer,textvariable=self.active_job,wraplength=1050).pack(anchor='w')
        ttk.Label(outer,textvariable=self.ai_status,wraplength=1050).pack(anchor='w')
        ttk.Label(outer,textvariable=self.status,font=('Segoe UI',11,'bold'),wraplength=1050).pack(anchor='w')
        self.progress=ttk.Progressbar(outer,maximum=100);self.progress.pack(fill='x',pady=5)
        ttk.Label(outer,text='STOP cere oprirea robotului și stingerea laserului. La pierderea USB, oprirea/stingerea nu este garantată: folosește întreruperea fizică a alimentării. Fără reluare automată.',wraplength=1050).pack(anchor='w')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.studio=Studio(root,self.generate_captured,self.new_photo,self.ai_error)
        self.poll_id=root.after(80,self.poll)
        if (DATA/'calibration.json').exists():
            self.load_cal()
        if (DATA/'laser.json').exists():
            try:
                profile=json.loads((DATA/'laser.json').read_text(encoding='utf-8'))
                if profile['samples']==self.samples:
                    self.laser_z.set(str(profile['z']));self.laser_speed.set(str(profile['speed']));self.laser_power.set(str(profile['power']))
            except (ValueError,KeyError,OSError):pass

    def error(self,e):
        self.status.set('Eroare: '+str(e))
        messagebox.showerror('Dobot',str(e))

    def ai_error(self,e):
        self.ai_status.set('AI: '+str(e))
        if self.studio and self.studio.state=='generating':self.studio.confirm()
        messagebox.showerror('Fotografie / AI',str(e))

    def cancel_ai(self):
        if self.ai_busy:
            self.ai_cancel.set();self.ai_status.set('Anulare AI solicitată; robotul continuă lucrarea curentă.')

    def background_ai(self,task,done):
        if self.ai_busy:return
        self.ai_busy=True;self.ai_cancel.clear()
        def worker():
            try:self.events.put(('ai_done',done,task()))
            except Exception as e:self.events.put(('ai_error',str(e),traceback.format_exc()))
        threading.Thread(target=worker,daemon=True).start()

    def background(self,task,done):
        if self.busy:
            self.status.set('Operație în curs. Folosește STOP pentru a o întrerupe.')
            return
        self.busy=True;self.cancel.clear()
        def worker():
            try:self.events.put(('done',done,task()))
            except Exception as e:self.events.put(('error',str(e),traceback.format_exc()))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        while not self.events.empty():
            item=self.events.get()
            if item[0]=='status':self.status.set(item[1])
            elif item[0]=='focus_on':
                if self.focus_active:
                    self.focus_status.set('LASER APRINS temporar · maximum 1 secundă în controller')
                    self.status.set('Probă laser: aprins temporar · STINGE / STOP întrerupe proba')
            elif item[0]=='ai_status':self.ai_status.set(item[1])
            elif item[0]=='ai_done':
                self.ai_busy=False
                if not self.close_pending:
                    try:item[1](item[2])
                    except Exception as e:self.ai_error(e)
            elif item[0]=='ai_error':
                self.ai_busy=False
                DATA.mkdir(exist_ok=True)
                with (DATA/'errors.log').open('a',encoding='utf-8') as f:f.write(item[2]+'\n')
                if not self.close_pending:self.ai_error(item[1])
            elif item[0]=='progress':self.progress['value']=item[1]
            elif item[0]=='done':
                self.busy=False
                self.finish_focus()
                try:item[1](item[2])
                except Exception as e:self.error(e)
            elif item[0]=='error':
                self.busy=False;self.dry_key=None
                self.finish_focus(failed=True)
                self.active_job.set('Robot: lucrare oprită / eroare');self.laser_safe.set(False)
                DATA.mkdir(exist_ok=True)
                with (DATA/'errors.log').open('a',encoding='utf-8') as f:f.write(item[2]+'\n')
                if self.robot and self.robot.fault:
                    try:self.robot.close()
                    except Exception:pass  # Original transport/stop error is shown below.
                    self.robot=None;self.connect_button['text']='Conectează USB'
                self.error(item[1])
        if self.close_pending and not self.busy and not self.ai_busy:
            self.finish_close();return
        self.poll_id=self.root.after(80,self.poll)

    def require_robot(self):
        if not self.robot:raise ValueError('Conectează robotul prin USB mai întâi')

    def tool_changed(self,event=None):
        if self.busy:
            if self.focus_active:self.stop()
            self.tool_mode.set(self.selected_mode);return
        self.selected_mode=self.tool_mode.get();self.laser_safe.set(False)
        laser=self.selected_mode=='Laser'
        if laser:self.laser_frame.pack(fill='x',after=self.cal_label,pady=5)
        else:self.laser_frame.pack_forget()
        self.probe_button['text']='Probă laser STINS' if laser else 'Probă cu pixul ridicat'
        self.run_button['text']='GRAVEAZĂ' if laser else 'DESENEAZĂ'
        self.position_help['text']=('Laser: Z constant la focalizare; fascicul stins între linii.\nPune unealta în interiorul foii. Proba folosește același Z, cu laserul stins.\nNu muta accesoriile cât timp robotul lucrează.' if laser else 'Pix: contact la Z calibrat + corecție; ridicare între linii.\nPune pixul deasupra foii, în interior. La final revine la poziția înaltă de pornire.')

    def focus_laser(self):
        if self.busy or self.close_pending:return
        try:
            self.require_robot()
            if self.tool_mode.get()!='Laser':raise ValueError('Selectează unealta Laser')
            if not self.laser_safe.get():
                raise ValueError('Confirmă zona protejată, ochelarii, materialul și alinierea înainte de aprindere')
        except Exception as e:self.error(e);return
        robot=self.robot
        self.focus_active=True;self.focus_button['state']='disabled'
        self.focus_status.set('Pregătire probă de focalizare…')
        self.active_job.set('Robot: probă laser de 1 secundă, fără mișcare')
        def task():
            robot.focus_laser(self.cancel,lambda:self.events.put(('focus_on',)))
        def done(_):
            self.status.set('Laser STINS · Ajustează înălțimea cu Unlock sau memorează Z laser.')
            self.active_job.set('Robot: probă de focalizare terminată')
            if self.disconnect_after_focus and not self.close_pending:
                self.disconnect_after_focus=False;self.connect()
        self.background(task,done)

    def finish_focus(self,failed=False):
        if not self.focus_active:return
        self.focus_active=False;self.focus_button['state']='normal'
        self.focus_status.set('Eroare la focalizare — verifică stingerea laserului.' if failed else 'Laser STINS · poți memora Z sau repeta proba')
        if failed:self.disconnect_after_focus=False

    def save_laser_profile(self):
        z=float(self.laser_z.get().replace(',','.'))
        speed=float(self.laser_speed.get().replace(',','.'));power=float(self.laser_power.get().replace(',','.'))
        if not all(math.isfinite(v) for v in (z,speed,power)) or speed<=0 or not 0<power<=100:
            raise ValueError('Setări laser: Z finit, viteză pozitivă, putere peste 0 și maximum 100%')
        DATA.mkdir(exist_ok=True)
        (DATA/'laser.json').write_text(json.dumps(dict(z=z,speed=speed,power=power,samples=self.samples)),encoding='utf-8')
        return z,speed,power

    def capture_laser_z(self):
        if self.busy:return
        try:
            self.require_robot()
            if not self.cal:raise ValueError('Calibrează mai întâi zona XY a foii')
        except Exception as e:self.error(e);return
        def task():
            self.robot.prepare_laser();self.robot.check_clear()
            a=self.robot.pose();time.sleep(.15);b=self.robot.pose()
            if math.dist(a[:3],b[:3])>.2:raise ValueError('Unealta se mișcă; eliberează Unlock')
            return b[2]
        def done(z):
            self.laser_z.set(f'{z:.3f}');self.save_laser_profile()
            self.status.set('Z laser memorat. Zona XY și Z-ul pixului sunt păstrate.')
        self.background(task,done)

    def refresh_ports(self):
        devices=list(list_ports.comports())
        self.ports['values']=[p.device for p in devices]
        if not self.robot and self.port.get() not in self.ports['values']:
            preferred=next((p.device for p in devices if p.vid==0x10c4 and p.pid==0xea60),None)
            if preferred:self.port.set(preferred)

    def connect(self):
        if self.focus_active:
            self.disconnect_after_focus=True;self.stop();return
        if self.busy:return
        if self.robot:
            robot=self.robot;self.robot=None;self.dry_key=None
            self.connect_button['text']='Conectează USB'
            try:robot.close();self.status.set('Deconectat')
            except Exception as e:self.error(e)
            return
        port=self.port.get().strip()
        self.focus_status.set('Focalizare: neactivată')
        def task():
            r=Robot(port)
            try:
                fp={'serial':r.rpc(0).rstrip(b'\0').decode('ascii',errors='replace'),'tool':r.rpc(60).hex(),'version':r.version}
                return r,fp,r.alarms(),r.pose()
            except Exception:r.close();raise
        def done(result):
            self.robot,fp,a,p=result
            self.current_fingerprint=fp;self.dry_key=None
            self.connect_button['text']='Deconectează'
            self.status.set(f'Magician {self.robot.version} · USB direct · Alarme: {a or "niciuna"} · XYZ {p[0]:.1f}, {p[1]:.1f}, {p[2]:.1f} mm')
        self.status.set('Conectare USB directă… Închide conexiunea din DobotLab dacă portul este ocupat.')
        self.background(task,done)

    def read_pose(self):
        try:self.require_robot()
        except Exception as e:self.error(e);return
        self.background(lambda:(self.robot.pose(),self.robot.alarms()),lambda v:self.status.set(f'XYZ: {v[0][0]:.2f}, {v[0][1]:.2f}, {v[0][2]:.2f} mm · J: {[round(x,1) for x in v[0][4:]]} · Alarme: {v[1] or "niciuna"}'))

    def capture(self):
        if self.busy:return
        try:
            self.require_robot()
            if len(self.samples)>=4:raise ValueError('Apasă Calibrare nouă pentru a reînregistra colțurile')
        except Exception as e:self.error(e);return
        def task():
            self.robot.check_clear()
            a=self.robot.pose();time.sleep(.15);b=self.robot.pose()
            if math.dist(a[:3],b[:3])>.2:raise ValueError('Pixul se mișcă. Eliberează Unlock și memorează din nou.')
            return b
        def done(p):
            self.samples.append(p);self.dry_key=None
            self.fingerprint=self.current_fingerprint
            self.refresh_corners()
            if len(self.samples)==4:
                self.cal=Calibration([p[:3] for p in self.samples])
                Kinematics(self.samples)
                DATA.mkdir(exist_ok=True)
                tmp=DATA/'calibration.tmp'
                tmp.write_text(json.dumps({'schema':1,'samples':self.samples,'fingerprint':self.fingerprint},indent=2),encoding='utf-8')
                tmp.replace(DATA/'calibration.json')
                self.fixed.set(True);self.cal_label['text']=f'Salvat: {self.cal.width:.1f} × {self.cal.height:.1f} mm\nZ contact = {self.cal.contact_z:.2f} mm (cel mai de sus)'
                self.status.set('Calibrare salvată. Alege SVG-ul și adu pixul în interiorul foii.')
                if self.file:self.preview()
            else:self.status.set('Memorat. Următorul: '+NAMES[len(self.samples)])
            self.paint()
        self.background(task,done)

    def refresh_corners(self):
        for i,label in enumerate(self.corner_labels):
            label['text']=NAMES[i]+('  '+', '.join(f'{v:.1f}' for v in self.samples[i][:3]) if i<len(self.samples) else '  —')
        self.capture_button['text']='Toate colțurile memorate' if len(self.samples)==4 else 'Memorează '+NAMES[len(self.samples)]

    def new_cal(self):
        if self.busy:return
        self.samples=[];self.cal=None;self.paths=[];self.dry_key=None;self.fixed.set(False)
        self.laser_z.set('');self.laser_safe.set(False)
        self.cal_label['text']='Calibrare nouă — atinge colțul 1';self.refresh_corners();self.paint()

    def load_cal(self):
        if self.busy:return
        try:
            data=json.loads((DATA/'calibration.json').read_text(encoding='utf-8'))
            if data['schema']!=1:raise ValueError('Versiune de calibrare necunoscută')
            cal=Calibration([p[:3] for p in data['samples']]);Kinematics(data['samples'])
            self.cal=cal;self.samples=data['samples'];self.fingerprint=data['fingerprint'];self.dry_key=None
            self.laser_z.set('');self.laser_safe.set(False)
            self.fixed.set(False);self.paths=[];self.refresh_corners()
            self.cal_label['text']=f'Încărcat: {cal.width:.1f} × {cal.height:.1f} mm\nZ contact = {cal.contact_z:.2f} mm (cel mai de sus)'
            if self.file:self.preview()
        except Exception as e:self.error(e)

    def choose_svg(self):
        if self.ai_busy:return
        name=filedialog.askopenfilename(title='Alege SVG cu trasee',filetypes=[('SVG','*.svg')],initialdir=ROOT/'examples')
        if name:
            self.studio.cancel_capture();self.studio.show()
            self.file=name;self.file_label['text']=Path(name).name;self.preview()

    def values(self):
        v={k:float(s.get().replace(',','.')) for k,s in self.settings.items()}
        if not all(math.isfinite(x) for x in v.values()):raise ValueError('Setări numerice invalide')
        if v['speed']<=0 or v['z_speed']<=0:raise ValueError('Viteza trebuie să fie mai mare decât zero')
        if v['join_gap']<0:raise ValueError('Distanța de unire trebuie să fie cel puțin zero')
        if v['lift']<0:raise ValueError('Ridicarea trebuie să fie cel puțin zero')
        v['brand']=self.brand.get()
        return v

    def invalidate_photo_result(self):
        self.file=None;self.paths=[];self.dry_key=None
        self.file_label['text']='Fotografie în pregătire';self.paint()

    def new_photo(self):
        if self.ai_busy or self.close_pending:return
        try:
            index=int(self.camera_index.get())
            if index<0:raise ValueError('Indexul camerei trebuie să fie cel puțin zero')
            self.invalidate_photo_result();self.studio.live(index)
        except Exception as e:self.error(e)

    def generate_photo(self):
        if self.ai_busy or self.close_pending:return
        photo=filedialog.askopenfilename(title='Alege fotografia (decupaj pătrat central)',filetypes=[('Fotografii','*.jpg *.jpeg *.png *.webp')])
        if not photo:return
        try:
            self.studio.selected(photo);self.invalidate_photo_result()
        except Exception as e:self.error(e)

    def generate_captured(self,image):
        if self.ai_busy or self.close_pending:return
        try:
            steps=int(self.ai_steps.get())
            if not 1<=steps<=100:raise ValueError('Pași AI: număr întreg între 1 și 100')
            photo=save_capture(image,ROOT/'captures')
        except Exception as e:self.ai_error(e);self.studio.confirm();return
        use_local=local_mode()
        if not use_local:
            password=simpledialog.askstring('GB10 · toni@100.111.144.112','Parola SSH (nu se salvează):',show='*',parent=self.root)
            if password is None:self.studio.confirm();return
        self.studio.generating()
        def task():
            if use_local:
                from .local_ai import generate
                return generate(photo,ROOT/'outputs',self.ai_cancel,lambda text:self.events.put(('ai_status',text)),steps=steps)
            from .gb10 import generate
            return generate(photo,ROOT/'outputs',password,self.ai_cancel,lambda text:self.events.put(('ai_status',text)),steps=steps)
        def done(path):
            self.file=str(path);self.file_label['text']=path.name;self.dry_key=None
            self.preview()
            self.ai_status.set('Următorul portret este pregătit. După schimbarea foii apasă DESENEAZĂ / GRAVEAZĂ.')
        self.background_ai(task,done)

    def preview(self):
        self.dry_key=None;self.paths=[]
        try:
            if not self.file:raise ValueError('Alege un SVG')
            v=self.values()
            self.preview_cal=self.cal or Calibration([[190,-40,0],[270,-40,0],[270,40,0],[190,40,0]])
            self.paths,info=load_svg(self.file,self.preview_cal,v['margin'],v['join_gap'],v['brand'])
            if self.studio:self.studio.set_result(render_paths(self.paths,self.preview_cal.width,self.preview_cal.height))
            self.info['text']=f'{len(self.paths)} trasee ({info["joined"]} uniri, {info["removed"]} sub 1 mm eliminate) · {info["width"]:.1f} × {info["height"]:.1f} mm · {info["length"]:.0f} mm de linie\n'+ '\n'.join(info['warnings'])
            if not self.busy:self.status.set('Previzualizare pregătită. Poți porni lucrarea; proba este opțională.')
        except Exception as e:self.error(e)
        self.paint()

    def paint(self):
        c=self.canvas;c.delete('all')
        w,h=c.winfo_width(),c.winfo_height();size=max(40,min(w-85,h-100));scale=size/80
        ox=(w-size)/2;oy=(h-size)/2
        c.create_rectangle(ox,oy,ox+size,oy+size,fill='white',outline='#bac5cc',width=2)
        for x,y,label in [(0,0,'1 · SS'),(80,0,'2 · DS'),(80,80,'3 · DJ'),(0,80,'4 · SJ')]:
            c.create_text(ox+x*scale,oy+y*scale+(-16 if y==0 else 16),text=label,fill='#233b50',font=('Segoe UI',10,'bold'))
        display_cal=self.cal or self.preview_cal
        if display_cal:
            sx=size/display_cal.width;sy=size/display_cal.height
            for p in self.paths:
                coords=[z for x,y in p for z in (ox+x*sx,oy+y*sy)]
                if len(coords)>=4:c.create_line(*coords,fill='#152f43',width=1)
        c.create_text(w/2,oy+size+42,text='Vedere de sus · proporțiile desenului sunt păstrate',fill='#536778')

    def run(self,dry):
        if self.busy:return
        try:
            self.require_robot()
            if not self.cal or not self.file:raise ValueError('Calibrează foaia și alege un SVG')
            if not self.fixed.get() or not self.clear.get():raise ValueError('Confirmă fixarea suportului și spațiul liber pentru pix și braț')
            if self.fingerprint!=self.current_fingerprint:raise ValueError('Robotul, versiunea sau offsetul uneltei diferă de calibrare. Recalibrează.')
            values=self.values()
            use_laser=self.tool_mode.get()=='Laser'
            if use_laser:
                if not dry and not self.laser_safe.get():
                    raise ValueError('Verifică alinierea XY, protecția laser și materialul înainte de gravare')
                z,speed,power=self.save_laser_profile()
                values.update(laser_z=z,speed=speed,laser_power=power)
            values['tool_mode']='Laser' if use_laser else 'Pix'
            paths,info=load_svg(self.file,self.cal,values['margin'],values['join_gap'],values['brand'])
            key=json.dumps([self.samples,paths,values],sort_keys=True)
            self.paths=paths;self.paint()
        except Exception as e:self.error(e);return
        robot=self.robot;cal=self.cal;samples=list(self.samples);fingerprint=dict(self.fingerprint)
        job_name=Path(self.file).parent.name+'/'+Path(self.file).name
        self.active_job.set(f'În execuție: {values["tool_mode"]} · {job_name}')
        self.focus_status.set('Focalizare: inactivă · vezi starea lucrării')
        self.laser_safe.set(False)
        self.progress['value']=0
        self.status.set('Verificare traseu…')
        def task():
            log={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'dry':dry,'settings':values,'completed':0}
            prepared=False
            try:
                if use_laser:
                    prepared=True;robot.prepare_laser()
                robot.check_clear()
                if robot.rpc(60).hex()!=fingerprint['tool']:raise ValueError('Offsetul uneltei a fost schimbat. Recalibrează.')
                start=robot.pose()
                model=Kinematics(samples+[start])
                def make_plan(grouped=False):
                    if use_laser:return build_laser_plan(cal,paths,start,values['laser_z'],dry,grouped)
                    return build_plan(cal,paths,start,values['lift'],values['offset'],dry,grouped)
                plan=make_plan()
                model.validate(plan,start,self.cancel)
                operations=make_plan(True)
                # CP controls XYZ, not wrist R. Screen both constant-R and
                # constant-J4 behavior over the entire base-angle envelope.
                bases=[model.inverse(p)[0] for p in [start[:4]]+plan]
                span=max(bases)-min(bases)
                for delta in (-span,span):
                    model.validate([p[:3]+[p[3]+delta] for p in plan],start,self.cancel)
                log.update(start=start,targets=len(plan),drawing_z=cal.contact_z+values['offset'],travel_z=cal.contact_z+values['offset']+values['lift'],park_z=max(start[2],cal.contact_z+values['offset']+values['lift']))
                if use_laser:log.update(drawing_z=values['laser_z'],travel_z=values['laser_z'],park_z=max(start[2],values['laser_z']))
                if self.cancel.is_set():raise ValueError('Oprit')
                action=('Probă laser stins' if dry else 'Gravare') if use_laser else ('Probă ridicată' if dry else 'Desenare')
                self.events.put(('status',action+f' · {len(plan)} segmente · poți pregăti următoarea fotografie'))
                prepared=True;robot.prepare(values['speed'],values['z_speed'])
                total=sum(len(points) for _,points in operations)
                log['targets']=total
                log['motion_mode']='CPLE laser / CP travel / PTP vertical' if use_laser else 'CP buffered / PTP vertical'
                completed=0
                for kind,points in operations:
                    if self.cancel.is_set():raise RobotError('Oprit de utilizator')
                    p=points[-1]
                    if kind=='laser':
                        robot.continuous_laser(points,values['laser_power'],self.cancel,lambda n:self.events.put(('progress',100*(completed+n)/total)))
                    elif kind=='cp':
                        robot.continuous(points,self.cancel,lambda n:self.events.put(('progress',100*(completed+n)/total)))
                    else:
                        robot.move(p,self.cancel)
                    robot.check_clear()
                    actual=robot.pose()
                    model.check(actual[:4])
                    if math.dist(actual[:3],p[:3])>.7 or (kind=='ptp' and abs(actual[3]-p[3])>.7):
                        raise RobotError('Poziția raportată nu corespunde comenzii. Execuție oprită.')
                    completed+=len(points)
                    log['completed']=completed
                    self.events.put(('progress',100*completed/total))
                log['success']=True
                return key
            except Exception as e:
                log['error']=str(e);raise
            finally:
                try:
                    if prepared:robot.stop()
                except Exception as e:
                    log['stop_error']=str(e)
                    raise
                finally:
                    DATA.mkdir(exist_ok=True)
                    (DATA/f'job-{time.time_ns()}.json').write_text(json.dumps(log,indent=2),encoding='utf-8')
        def done(key):
            if dry:self.dry_key=key
            self.progress['value']=100
            self.active_job.set(f'Terminat: {values["tool_mode"]} · {job_name}')
            self.status.set('Laser oprit · lucrare terminată, unealta la poziția de parcare.' if use_laser else ('Probă terminată.' if dry else 'Desen terminat · pix ridicat la poziția de pornire.'))
        self.background(task,done)

    def stop(self):
        if self.busy:
            self.cancel.set();self.dry_key=None;self.status.set('Oprire și stingere solicitate… Fără ridicare automată.')
        elif self.robot:
            if self.tool_mode.get()=='Laser':self.robot.laser_session=True
            self.background(self.robot.stop,lambda _:self.status.set('Controller oprit; coadă golită.'))

    def close(self):
        if self.busy or self.ai_busy:
            self.close_pending=True;self.cancel_ai();self.stop()
        else:
            self.root.after_cancel(self.poll_id)
            self.finish_close()

    def finish_close(self):
        try:
            if self.robot:self.robot.close()
        except Exception as e:
            self.error(f'Oprire la închidere neconfirmată: {e}. Întrerupe fizic alimentarea laserului.')
        finally:
            self.robot=None
            if self.studio:self.studio.close()
            self.root.destroy()


def main():
    root=tk.Tk();App(root);root.mainloop()


if __name__=='__main__':main()
