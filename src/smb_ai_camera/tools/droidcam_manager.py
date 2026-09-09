import cv2
import threading
import time
import os
import numpy as np
from typing import Optional, Tuple, Union

# Suppress noisy OpenCV backend warnings
os.environ["OPENCV_VIDEOIO_PRIORITY_MSMF"] = "1"

class DroidCamManager:
    """
    Manages non-blocking real-time video stream from DroidCam (Android Phone/Tablet).
    Supports:
      - IP Stream URL: http://<phone_ip>:4747/video (or /mjpegfeed)
      - USB / Virtual Webcam Device Index: 0, 1, 2...
    """
    def __init__(self, default_source: Union[str, int] = "1"):
        self.source = default_source
        self.cap: Optional[cv2.VideoCapture] = None
        self.is_running = False
        self.is_connected = False
        self.last_frame: Optional[np.ndarray] = None
        self.last_analyzed_frame: Optional[np.ndarray] = None
        self.last_analysis: dict = {}
        self.lock = threading.Lock()
        self.fps = 0.0
        self.thread: Optional[threading.Thread] = None

    def start(self, source: Optional[Union[str, int]] = None):
        if source is not None:
            self.source = source
        self.is_running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print(f"[DroidCamManager] Stream capture thread started on source: {self.source}")

    def stop(self):
        self.is_running = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.is_connected = False
        print("[DroidCamManager] Stream stopped.")

    def set_source(self, source: Union[str, int]):
        """
        Dynamically updates the DroidCam source (IP or device index).
        """
        with self.lock:
            self.source = source
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            self.is_connected = False
            self.last_frame = None
        print(f"[DroidCamManager] Source switched to: {source}")

    def get_latest_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            if self.last_frame is not None:
                return True, self.last_frame.copy()
            return False, None

    def update_analysis(self, analyzed_frame: np.ndarray, analysis: dict):
        with self.lock:
            self.last_analyzed_frame = analyzed_frame
            self.last_analysis = analysis

    def get_latest_analysis(self) -> Tuple[Optional[np.ndarray], dict]:
        with self.lock:
            frame = self.last_analyzed_frame.copy() if self.last_analyzed_frame is not None else None
            return frame, dict(self.last_analysis)

    def _open_capture(self, src: Union[str, int]) -> Optional[cv2.VideoCapture]:
        is_index = False
        if isinstance(src, int) or (isinstance(src, str) and src.isdigit()):
            src_val = int(src)
            is_index = True
        else:
            src_val = str(src).strip()

        cap = None
        if is_index:
            # Try default backend first (MSMF on Windows, avoids C++ DSHOW exceptions)
            try:
                cap = cv2.VideoCapture(src_val)
                if not cap.isOpened():
                    cap.release()
                    cap = cv2.VideoCapture(src_val, cv2.CAP_DSHOW)
            except Exception:
                try:
                    cap = cv2.VideoCapture(src_val, cv2.CAP_DSHOW)
                except Exception:
                    cap = None
        else:
            try:
                cap = cv2.VideoCapture(src_val)
            except Exception:
                cap = None

        if cap and cap.isOpened():
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            except Exception:
                pass
            return cap
        elif cap:
            cap.release()
        return None

    def _capture_loop(self):
        fps_counter = 0
        fps_timer = time.time()

        while self.is_running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    cap = self._open_capture(self.source)
                    if cap is None:
                        self.is_connected = False
                        time.sleep(1.5)
                        continue

                    self.cap = cap
                    self.is_connected = True
                    print(f"[DroidCamManager] Successfully opened video source: {self.source}")

                ret, frame = self.cap.read()
                if not ret or frame is None:
                    self.is_connected = False
                    if self.cap:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                        self.cap = None
                    time.sleep(0.8)
                    continue

                with self.lock:
                    self.last_frame = frame
                    self.is_connected = True

                fps_counter += 1
                if time.time() - fps_timer >= 1.0:
                    self.fps = round(fps_counter / (time.time() - fps_timer), 1)
                    fps_counter = 0
                    fps_timer = time.time()

                time.sleep(0.015) # ~60 FPS cap

            except Exception as e:
                print(f"[DroidCamManager] Error in capture loop: {e}")
                self.is_connected = False
                time.sleep(1.0)
