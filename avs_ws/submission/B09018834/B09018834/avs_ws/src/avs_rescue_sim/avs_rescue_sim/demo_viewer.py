#!/usr/bin/env python3
"""Live camera and event windows for the ordinary four-window demonstration."""

import json
import os
import signal
import sys
import time

from PyQt5 import QtCore, QtGui, QtWidgets
import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from rclpy.signals import SignalHandlerOptions
from sensor_msgs.msg import Image
from std_msgs.msg import String

from avs_rescue_sim.demo_layout import NativeWindowLayout


def prepare_qt_environment():
    """Ignore OpenCV's bundled Qt plugins if an importing parent exported them."""
    for key in ('QT_QPA_PLATFORM_PLUGIN_PATH', 'QT_QPA_FONTDIR'):
        if '/cv2/' in os.environ.get(key, ''):
            os.environ.pop(key, None)


def screen_slots(geometry):
    """Return four frame rectangles within the desktop's usable area."""
    gap = 8
    area = geometry.adjusted(gap, gap, -gap, -gap)
    top_height = int((area.height() - gap) * .60)
    bottom_height = area.height() - gap - top_height
    gazebo_width = int((area.width() - gap) * .60)
    camera_width = int((area.width() - gap) * .35)
    bottom_y = area.y() + top_height + gap
    return {
        'gazebo': QtCore.QRect(area.x(), area.y(), gazebo_width, top_height),
        'rviz': QtCore.QRect(area.x() + gazebo_width + gap, area.y(),
                            area.width() - gap - gazebo_width, top_height),
        'camera': QtCore.QRect(area.x(), bottom_y, camera_width, bottom_height),
        'events': QtCore.QRect(area.x() + camera_width + gap, bottom_y,
                              area.width() - gap - camera_width, bottom_height),
    }


def place_window(window, rectangle):
    """Allow space for window-manager decorations as well as the client area."""
    extra_width = max(0, window.frameGeometry().width() - window.width())
    extra_height = max(0, window.frameGeometry().height() - window.height())
    window.resize(max(1, rectangle.width() - extra_width),
                  max(1, rectangle.height() - extra_height))
    window.move(rectangle.topLeft())


def image_to_qimage(message):
    """Decode ROS bytes without cv_bridge/OpenCV; retain padding and own pixels."""
    encoding = message.encoding.lower()
    formats = {
        'rgb8': (3, QtGui.QImage.Format_RGB888, False),
        'bgr8': (3, QtGui.QImage.Format_RGB888, True),
        'rgba8': (4, QtGui.QImage.Format_RGBA8888, False),
        'bgra8': (4, QtGui.QImage.Format_RGBA8888, True),
        'mono8': (1, QtGui.QImage.Format_Grayscale8, False),
    }
    if encoding not in formats:
        raise ValueError(f'unsupported image encoding: {message.encoding}')
    channels, image_format, swap = formats[encoding]
    width, height, stride = message.width, message.height, message.step
    if width <= 0 or height <= 0 or stride < width * channels:
        raise ValueError(f'invalid image dimensions/stride: {width}x{height}, step={stride}')
    data = bytes(message.data)
    if len(data) < stride * height:
        raise ValueError(f'incomplete image: {len(data)} bytes, expected {stride * height}')
    image = QtGui.QImage(data, width, height, stride, image_format)
    if image.isNull():
        raise ValueError('Qt could not decode the image')
    # QImage otherwise borrows the bytes, which are local to this callback.
    return image.rgbSwapped() if swap else image.copy()


class CameraCanvas(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.image = None

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor('#101820'))
        if self.image is None:
            painter.setPen(QtGui.QColor('#d3e7f5'))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, '等待处理后的相机画面…')
            return
        size = self.image.size().scaled(self.size(), QtCore.Qt.KeepAspectRatio)
        target = QtCore.QRect(QtCore.QPoint((self.width() - size.width()) // 2,
                                           (self.height() - size.height()) // 2), size)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawImage(target, self.image)


class DemoViewer(Node):
    def __init__(self):
        super().__init__('demo_viewer')
        self.gazebo_pid = self.declare_parameter('gazebo_pid', 0).value
        self.rviz_pid = self.declare_parameter('rviz_pid', 0).value
        self.camera_window = QtWidgets.QWidget()
        self.camera_window.setWindowTitle('AVS 3/4 — ONBOARD CAMERA · 车载识别画面')
        camera_layout = QtWidgets.QVBoxLayout(self.camera_window)
        camera_layout.setContentsMargins(8, 6, 8, 6)
        self.camera_status = QtWidgets.QLabel('等待视觉节点发布图像…')
        self.camera_status.setTextFormat(QtCore.Qt.PlainText)
        self.camera_status.setWordWrap(True)
        self.camera_canvas = CameraCanvas()
        camera_layout.addWidget(self.camera_status)
        camera_layout.addWidget(self.camera_canvas, 1)

        self.events_window = QtWidgets.QWidget()
        self.events_window.setWindowTitle('AVS 4/4 — LIVE EVENTS · 任务与识别日志')
        event_layout = QtWidgets.QVBoxLayout(self.events_window)
        event_layout.setContentsMargins(8, 6, 8, 6)
        self.clock_label = QtWidgets.QLabel()
        self.mission_label = QtWidgets.QLabel('任务状态：等待任务节点启动…')
        self.mission_label.setTextFormat(QtCore.Qt.PlainText)
        self.mission_label.setWordWrap(True)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(200)
        self.log_view.setFont(QtGui.QFont('monospace', 10))
        event_layout.addWidget(self.clock_label)
        event_layout.addWidget(self.mission_label)
        event_layout.addWidget(self.log_view, 1)
        for window in (self.camera_window, self.events_window):
            window.setStyleSheet('QWidget { background: #182634; color: #e0f2ff; }'
                                'QPlainTextEdit { background: #101820; border: 0; }')

        self.started = time.monotonic()
        self.last_frame_at = None
        self.pending_frame = None
        self.last_image_error = None
        self.last_safety = None
        self.last_clock_update = 0.
        self.last_camera_render = 0.
        self.mission_state = None
        self.corridor = set()
        self.core = set()
        retained = QoSProfile(depth=20, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(Image, '/camera/annotated', self.camera_callback,
                                 qos_profile_sensor_data)
        self.create_subscription(String, '/mission/status', self.mission_callback, retained)
        self.create_subscription(String, '/hazards/detections', self.detection_callback, retained)
        self.create_subscription(String, '/safety/status', self.safety_callback, 10)
        self.append_event('AVS', '实时展示已启动，等待任务与识别消息。')

    def append_event(self, category, detail):
        # Each message remains one bounded log block, including malformed data.
        detail = ' '.join(str(detail).splitlines())[:1600]
        self.log_view.appendPlainText(f'[{time.strftime("%H:%M:%S")}] [{category}] {detail}')

    def parse_event(self, message, category):
        try:
            payload = json.loads(message.data)
            if not isinstance(payload, dict):
                raise ValueError('expected a JSON object')
            return payload
        except (ValueError, TypeError) as exc:
            self.append_event('ERROR', f'{category} 消息无效：{exc}')
            return None

    def camera_callback(self, message):
        # Keep only the newest frame if rendering falls behind the publisher.
        self.pending_frame = message

    def mission_callback(self, message):
        event = self.parse_event(message, 'MISSION')
        if event is None:
            return
        self.mission_state = event
        step = f' [{event["step"]}]' if event.get('step') else ''
        self.append_event('MISSION', f'{event.get("state", "unknown")}{step}: '
                                    f'{event.get("detail", "")}')
        self.update_mission_label()

    def update_mission_label(self):
        if self.mission_state is None:
            return
        event = self.mission_state
        self.mission_label.setText(
            f'任务：{event.get("state", "unknown")}  {event.get("step", "")}  |  '
            f'走廊 {max(len(self.corridor), self.count(event.get("corridor_detected")))}/5'
            f'  核心 {max(len(self.core), self.count(event.get("core_detected")))}/4')

    @staticmethod
    def count(value):
        try:
            return max(0, int(value))
        except (ValueError, TypeError, OverflowError):
            return 0

    @staticmethod
    def coordinate(value):
        try:
            return f'{float(value):.3f}'
        except (ValueError, TypeError, OverflowError):
            return '?'

    def detection_callback(self, message):
        event = self.parse_event(message, 'DETECTION')
        if event is None:
            return
        label = str(event.get('label', 'unknown'))
        if event.get('kind') == 'corridor_hazard':
            self.corridor.add(label)
            self.append_event(f'CORRIDOR {len(self.corridor)}/5', f'confirmed {label}')
        elif event.get('kind') == 'core_hazard':
            tag = str(event.get('tag_id', '?'))
            self.core.add(tag)
            self.append_event(f'CORE {len(self.core)}/4',
                              f'AprilTag {tag} {label} at map '
                              f'({self.coordinate(event.get("map_x"))}, '
                              f'{self.coordinate(event.get("map_y"))}) m')
        else:
            self.append_event('DETECTION', json.dumps(event, ensure_ascii=False))
        self.update_mission_label()

    def safety_callback(self, message):
        event = self.parse_event(message, 'SAFETY')
        if event is None:
            return
        state = (bool(event.get('blocked')), str(event.get('reason', '')),
                 bool(event.get('pushing')))
        if state != self.last_safety:
            blocked, reason, pushing = state
            self.append_event('SAFETY', f'{"阻停" if blocked else "监控"}: '
                              f'{reason or "clear"}' + (' · 推障模式' if pushing else ''))
            self.last_safety = state

    def refresh(self):
        now = time.monotonic()
        if self.pending_frame is not None and now - self.last_camera_render >= .05:
            message, self.pending_frame = self.pending_frame, None
            self.last_camera_render = now
            try:
                self.camera_canvas.image = image_to_qimage(message)
                self.camera_canvas.update()
                if self.last_frame_at is None:
                    self.get_logger().info(
                        f'AVS live camera receiving /camera/annotated '
                        f'({message.width}x{message.height}, {message.encoding})')
                self.last_frame_at = now
                self.last_image_error = None
            except (ValueError, TypeError, OverflowError) as exc:
                error = str(exc)
                if error != self.last_image_error:
                    self.append_event('CAMERA ERROR', error)
                self.last_image_error = error
        if now - self.last_clock_update < .25:
            return
        self.last_clock_update = now
        self.clock_label.setText(time.strftime('系统时间：%Y-%m-%d %H:%M:%S')
                                 + f'  |  展示运行 {int(now - self.started)} 秒')
        if self.last_image_error:
            status = f'图像异常：{self.last_image_error}'
        elif self.last_frame_at is None:
            status = '等待视觉节点发布处理后的图像…'
        elif now - self.last_frame_at > 2.:
            status = f'等待新画面：已 {now - self.last_frame_at:.1f} 秒未更新'
        else:
            status = '车载相机 · 实时识别结果'
        self.camera_status.setText(status)


def main(args=None):
    prepare_qt_environment()
    app = QtWidgets.QApplication(sys.argv[:1])
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    viewer = None
    executor = None
    native_layout = None
    timer = QtCore.QTimer()
    previous_handlers = {}
    try:
        viewer = DemoViewer()
        executor = SingleThreadedExecutor(context=viewer.context)
        executor.add_node(viewer)
        slots = screen_slots(app.primaryScreen().availableGeometry())
        native_layout = NativeWindowLayout(
            {'gazebo': viewer.gazebo_pid, 'rviz': viewer.rviz_pid}, slots)
        viewer.camera_window.show()
        place_window(viewer.camera_window, slots['camera'])

        def show_events():
            viewer.events_window.show()
            place_window(viewer.events_window, slots['events'])

        QtCore.QTimer.singleShot(650, show_events)

        def tick():
            if not rclpy.ok():
                app.quit()
                return
            try:
                # Every spin is nonblocking and this bounded batch leaves Qt time
                # to paint and handle close events, even under a topic backlog.
                for _ in range(8):
                    executor.spin_once(timeout_sec=0.)
                viewer.refresh()
                native_layout.poll()
            except (ExternalShutdownException, KeyboardInterrupt):
                app.quit()

        timer.timeout.connect(tick)
        timer.start(20)
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda *_: app.quit())
        app.exec_()
    finally:
        timer.stop()
        if native_layout is not None:
            native_layout.close()
        if executor is not None:
            executor.shutdown()
        if viewer is not None:
            viewer.camera_window.close()
            viewer.events_window.close()
            viewer.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    main()
