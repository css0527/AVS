#!/usr/bin/env python3
"""Record an uninterrupted one-click run in a dedicated competition window."""
import argparse
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import time
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR']='0'
os.environ['QT_SCALE_FACTOR']='1'
os.environ['QT_ENABLE_HIGHDPI_SCALING']='0'
from PyQt5 import QtCore, QtGui, QtWidgets

WORKSPACE=Path(__file__).resolve().parents[3]


def write_metadata(output, metadata):
    """Replace the status atomically, including when recording stops early."""
    temporary=output/'recording.json.tmp'
    temporary.write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    temporary.replace(output/'recording.json')


def stop_child(process, *, group=False, recorder=False):
    """Bound shutdown even when ffmpeg cannot flush or a launch child stalls."""
    if process is None or process.poll() is not None:return 'already_exited'
    try:
        if recorder:
            process.communicate(b'q',timeout=15)
        else:
            if group:os.killpg(process.pid,signal.SIGINT)
            else:process.terminate()
            process.wait(timeout=15)
        return 'graceful'
    except (subprocess.TimeoutExpired,BrokenPipeError,ProcessLookupError):
        pass
    try:
        if process.poll() is None:
            if group:os.killpg(process.pid,signal.SIGTERM)
            else:process.terminate()
        process.wait(timeout=5)
        return 'terminated_after_grace_period'
    except subprocess.TimeoutExpired:
        if group:os.killpg(process.pid,signal.SIGKILL)
        else:process.kill()
        process.wait(timeout=5)
        return 'killed_after_grace_period'


class Presentation(QtWidgets.QWidget):
    def __init__(self, output, nested, metadata):
        super().__init__()
        self.output=output;output.mkdir(parents=True,exist_ok=True)
        self.nested=nested;self.metadata=metadata;self.cleaned=False;self.exit_reason=None
        self.setWindowTitle('AVS Competition — continuous demonstration')
        self.setFixedSize(1920,1080)
        self.move(0,0)
        self.x11=ctypes.CDLL(ctypes.util.find_library("X11"))
        self.x11.XOpenDisplay.restype=ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes=[ctypes.c_char_p]
        self.x11.XMoveResizeWindow.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_uint]
        self.x11.XRaiseWindow.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        self.x11.XFlush.argtypes=[ctypes.c_void_p]
        # The ROS launch may close a native view between two presentation ticks.
        self.xerror_callback=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p)(lambda *_:0)
        self.x11.XSetErrorHandler.argtypes=[type(self.xerror_callback)]
        self.x11.XSetErrorHandler(self.xerror_callback)
        self.display=self.x11.XOpenDisplay(None)
        if not self.display:raise RuntimeError("Cannot connect to the isolated recording display")
        self.clock=QtWidgets.QLabel(self);self.clock.setStyleSheet('font: bold 20px monospace; color: white; background:#182634')
        self.clock.setGeometry(10,10,1900,35)
        self.containers={}
        for name,x,w in [('Gazebo',10,1130),('RViz',1150,760)]:
            placeholder=QtWidgets.QLabel(name+' — starting',self)
            placeholder.setGeometry(x,65,w,600)
        self.camera_title=QtWidgets.QLabel('ONBOARD CAMERA — recognition results',self)
        self.camera_title.setStyleSheet('font: bold 16px monospace; color: white; background:#182634')
        self.camera_title.setGeometry(10,675,520,25)
        self.camera_view=QtWidgets.QLabel('Waiting for camera…',self)
        self.camera_view.setGeometry(10,700,520,370)
        self.camera_view.setAlignment(QtCore.Qt.AlignCenter)
        self.camera_view.setStyleSheet('color: white; background:#101820')
        self.camera_stamp=None;self.camera_seen=None;self.camera_frames=0
        self.logview=QtWidgets.QPlainTextEdit(self);self.logview.setReadOnly(True)
        self.logview.setGeometry(540,675,1370,395)
        self.logview.setStyleSheet('font: 14px monospace; color:#e0f2ff; background:#101820')
        self.process=None;self.recorder=None;self.started=None;self.terminal=None;self.logfile=None
        self.timer=QtCore.QTimer();self.timer.timeout.connect(self.tick);self.timer.start(125)
        QtCore.QTimer.singleShot(1000,self.start)

    def start(self):
        if self.cleaned:return
        try:self.start_recording()
        except Exception as exc:
            self.exit_reason='startup_failed'
            self.metadata['errors'].append(f'start: {exc}')
            self.close()

    def start_recording(self):
        # Capture the dedicated nested X display. Gazebo uses native OpenGL child
        # windows, which are not reliably captured through an embedded Qt parent.
        # This display contains only our presentation and the two simulator views.
        self.recorder=subprocess.Popen(['ffmpeg','-y','-hide_banner','-loglevel','error',
            '-f','x11grab','-draw_mouse','0',
            '-framerate','15','-video_size',f'{self.width()}x{self.height()}',
            '-i',os.environ['DISPLAY'],'-vf','format=yuv420p',
            '-c:v','libx264','-threads','2','-preset','ultrafast','-crf','25',
            '-movflags','+frag_keyframe+empty_moov',str(self.output/'continuous_raw.mp4')],stdin=subprocess.PIPE)
        self.logfile=(self.output/'recording_launch.log').open('w')
        env=os.environ.copy();env['ROS_LOG_DIR']=str(self.output/'ros')
        self.process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('run_acceptance.py')),
            '--gui','--images','--presentation','--mapping-evidence','--output',str(self.output/'evidence')],env=env,
            stdout=self.logfile,stderr=subprocess.STDOUT,start_new_session=True)
        self.started=time.monotonic()
        self.metadata.update(status='recording',recording_started_at=time.time(),
                             ffmpeg_pid=self.recorder.pid,acceptance_pid=self.process.pid)
        write_metadata(self.output,self.metadata)

    def embed(self, name, pid):
        # Only root children are application windows. The recursive tree also
        # contains Gazebo's large render widget, which must never be moved alone.
        tree=subprocess.run(['xwininfo','-root','-children'],capture_output=True,text=True).stdout
        for line in tree.splitlines():
            if not re.search(r'gazebo|rviz',line,re.I):continue
            m=re.search(r'(0x[0-9a-f]+)',line)
            if not m:continue
            wid=m.group(1)
            prop=subprocess.run(['xprop','-id',wid,'_NET_WM_PID'],capture_output=True,text=True).stdout
            if not prop.strip().endswith('= '+pid):continue
            info=subprocess.run(['xwininfo','-id',wid],capture_output=True,text=True).stdout
            width=re.search(r'Width: (\d+)',info)
            height=re.search(r'Height: (\d+)',info)
            if ('IsViewable' not in info or not width or not height
                    or int(width.group(1))<400 or int(height.group(1))<400):continue
            self.containers[name]=int(wid,16)
            self.position_windows()
            return

    def position_windows(self):
        # Keep the native windows above the presentation's blank slots. No window
        # manager runs in Xephyr, so these explicit root coordinates are stable.
        for name,wid in self.containers.items():
            x,y,w,h=(10,65,1130,600) if name=='Gazebo' else (1150,65,760,600)
            self.x11.XMoveResizeWindow(self.display,wid,x,y,w,h)
            self.x11.XRaiseWindow(self.display,wid)
        self.x11.XFlush(self.display)

    def tick(self):
        if self.cleaned:return
        try:self.update_presentation()
        except Exception as exc:
            self.exit_reason='presentation_failed'
            self.metadata['errors'].append(f'tick: {exc}')
            self.close()

    def update_presentation(self):
        if self.nested.poll() is not None:
            self.exit_reason='xephyr_exited'
            self.close()
            return
        if self.recorder is not None and self.recorder.poll() is not None:
            self.exit_reason='ffmpeg_exited_early'
            self.close()
            return
        elapsed=0 if self.started is None else time.monotonic()-self.started
        self.clock.setText(time.strftime('System time: %Y-%m-%d %H:%M:%S')+f'     Elapsed: {elapsed:.1f}s     Live recording')
        if self.process is None:return
        preview=self.output/'evidence'/'camera_live.jpg'
        try:
            stamp=preview.stat().st_mtime_ns
            if stamp!=self.camera_stamp:
                frame=QtGui.QPixmap(str(preview))
                if not frame.isNull():
                    self.camera_view.setPixmap(frame.scaled(self.camera_view.size(),QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
                    self.camera_stamp=stamp;self.camera_seen=time.monotonic();self.camera_frames+=1
                    self.camera_title.setText('ONBOARD CAMERA — recognition results')
        except FileNotFoundError:pass
        if self.camera_seen and time.monotonic()-self.camera_seen>2:
            self.camera_title.setText('ONBOARD CAMERA — waiting for new frame')
        launch=self.output/'evidence'/'launch.log'
        text=launch.read_text(errors='replace') if launch.exists() else (self.output/'recording_launch.log').read_text(errors='replace')
        text=re.sub(r'\x1b\[[0-9;]*m','',text)
        lines=[line for line in text.splitlines() if any(s in line for s in ['MISSION','CORRIDOR','CORE','AVS ','Summary:','Starting >>>','Finished <<<'])]
        self.logview.setPlainText('\n'.join(lines[-18:]))
        for name,pattern in [('Gazebo',r'\[gzclient-\d+\]: process started with pid \[(\d+)\]'),('RViz',r'\[rviz2-\d+\]: process started with pid \[(\d+)\]')]:
            match=re.search(pattern,text)
            if match and name not in self.containers:self.embed(name,match.group(1))
        self.position_windows()
        if self.process.poll() is not None:
            self.terminal=self.terminal or time.monotonic()
            if time.monotonic()-self.terminal>5:
                self.exit_reason='acceptance_completed' if self.process.returncode==0 else 'acceptance_failed'
                self.close()
        if elapsed>600 and not self.cleaned:
            self.exit_reason='recording_timeout'
            self.close()

    def cleanup(self, reason=None):
        if self.cleaned:return
        self.cleaned=True
        self.timer.stop()
        self.exit_reason=self.exit_reason or reason or 'window_closed'
        self.metadata.update(status='stopping',exit_reason=self.exit_reason,
                             camera_frames_shown=self.camera_frames,continuous=False)
        try:write_metadata(self.output,self.metadata)
        except Exception as exc:self.metadata['errors'].append(f'status before cleanup: {exc}')
        try:
            try:self.metadata['ffmpeg_shutdown']=stop_child(self.recorder,recorder=True)
            except Exception as exc:self.metadata['errors'].append(f'ffmpeg cleanup: {exc}')
            finally:self.metadata['ffmpeg_exit_code']=None if self.recorder is None else self.recorder.poll()
        finally:
            try:
                try:self.metadata['acceptance_shutdown']=stop_child(self.process,group=True)
                except Exception as exc:self.metadata['errors'].append(f'acceptance cleanup: {exc}')
                finally:self.metadata['acceptance_exit_code']=None if self.process is None else self.process.poll()
            finally:
                try:
                    if self.logfile:self.logfile.close()
                except Exception as exc:self.metadata['errors'].append(f'log cleanup: {exc}')
                finally:
                    complete=(self.exit_reason=='acceptance_completed'
                              and self.metadata['ffmpeg_exit_code']==0
                              and self.metadata.get('ffmpeg_shutdown')=='graceful'
                              and self.metadata['acceptance_exit_code']==0
                              and self.nested.poll() is None and not self.metadata['errors'])
                    self.metadata.update(continuous=complete,status='recorded' if complete else 'failed',
                                         recording_ended_at=time.time(),xephyr_exit_code=self.nested.poll())
                    write_metadata(self.output,self.metadata)

    def closeEvent(self,event):
        self.cleanup()
        event.accept()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=WORKSPACE/'submission'/'recording')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    metadata={'status':'starting','created_at':time.time(),'continuous':False,
              'camera_topic':'/camera/annotated','camera_frames_shown':0,
              'resolution':[1920,1080],'exit_reason':None,'ffmpeg_exit_code':None,
              'acceptance_exit_code':None,'xephyr_exit_code':None,'errors':[]}
    write_metadata(output,metadata)
    nested=None;panel=None;nested_log=None
    try:
        if not shutil.which('Xephyr'):
            raise RuntimeError('Install xserver-xephyr to record the isolated demonstration desktop.')
        display=next(f':{n}' for n in range(90,120) if not Path(f'/tmp/.X11-unix/X{n}').exists())
        nested_log=(output/'xephyr.log').open('w')
        nested=subprocess.Popen(['Xephyr',display,'-screen','1920x1080','-dpi','96',
            '-ac','-noreset','-nolisten','tcp','-title','AVS isolated competition recording'],
            stdout=nested_log,stderr=subprocess.STDOUT,start_new_session=True)
        metadata.update(xephyr_pid=nested.pid,display=display)
        write_metadata(output,metadata)
        for _ in range(60):
            if nested.poll() is not None:raise RuntimeError('Xephyr failed to start; see xephyr.log')
            if Path('/tmp/.X11-unix/X'+display[1:]).exists():break
            time.sleep(.05)
        else:raise RuntimeError('Xephyr display did not become ready')
        os.environ.update(DISPLAY=display,QT_FONT_DPI='96',QT_QPA_PLATFORM='xcb')
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_DisableHighDpiScaling)
        app=QtWidgets.QApplication(sys.argv[:1]);panel=Presentation(output,nested,metadata);panel.show()
        def interrupted(signum, _frame):
            panel.exit_reason=f'signal_{signal.Signals(signum).name}'
            panel.close()
        signal.signal(signal.SIGINT,interrupted)
        signal.signal(signal.SIGTERM,interrupted)
        app.exec_()
    except BaseException as exc:
        metadata.update(status='failed',continuous=False,exit_reason='recorder_exception')
        metadata['errors'].append(f'main: {type(exc).__name__}: {exc}')
        raise
    finally:
        try:
            if panel:panel.cleanup('application_exited')
        except Exception as exc:
            metadata.update(status='failed',continuous=False)
            metadata['errors'].append(f'final cleanup: {exc}')
        finally:
            try:
                metadata['xephyr_shutdown_requested']=bool(nested and nested.poll() is None)
                metadata['xephyr_shutdown']=stop_child(nested)
            except Exception as exc:
                metadata.update(status='failed',continuous=False)
                metadata['errors'].append(f'Xephyr cleanup: {exc}')
            finally:
                metadata['xephyr_exit_code']=None if nested is None else nested.poll()
                try:
                    if nested_log:nested_log.close()
                except Exception as exc:
                    metadata['errors'].append(f'Xephyr log cleanup: {exc}')
                finally:write_metadata(output,metadata)
    raw=output/'continuous_raw.mp4'
    evidence=output/'evidence'/'evaluation.json'
    try:
        if not metadata['continuous']:
            raise RuntimeError('Recording ended incompletely; see recording.json. Raw recording retained.')
        if not evidence.exists() or not json.loads(evidence.read_text())['passed']:
            raise RuntimeError('Run did not pass acceptance; raw recording retained, no submission video produced.')
        if panel.camera_frames<10:
            raise RuntimeError('Onboard camera was not visible; raw recording retained, no submission video produced.')
        duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration',
            '-of','default=noprint_wrappers=1:nokey=1',str(raw)],text=True))
        speed=max(1,int(duration/295)+1)
        filters=f'setpts=PTS/{speed},drawbox=x=1530:y=0:w=390:h=55:color=black:t=fill,drawtext=text=Playback {speed}x:x=1570:y=15:fontsize=26:fontcolor=white'
        target=output.parent/'competition_demo.mp4'
        subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',str(raw),'-an',
            '-vf',filters,'-r','15','-c:v','libx264','-threads','2','-preset','fast','-crf','26',
            '-movflags','+faststart',str(target)],check=True)
        if target.stat().st_size>100_000_000:
            raise RuntimeError('Video exceeds 100 MB; reduce bitrate before submission.')
        metadata.update(status='complete',video=str(target),raw_duration_s=duration,playback_speed=speed)
    except Exception as exc:
        metadata.update(status='failed',export_error=str(exc))
        raise SystemExit(str(exc))
    finally:write_metadata(output,metadata)
    print(target)


if __name__=='__main__':main()
