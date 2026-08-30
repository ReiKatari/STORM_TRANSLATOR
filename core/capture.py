import mss
import mss.tools
from PIL import Image

class ScreenCapturer:
    def __init__(self):
        self.sct = mss.mss()

    def capture_area(self, x, y, width, height):
        try:
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app and app.primaryScreen():
                ratio = app.primaryScreen().devicePixelRatioF()
                x = int(x * ratio)
                y = int(y * ratio)
                width = int(width * ratio)
                height = int(height * ratio)
        except Exception as e:
            pass
            
        monitor = {"top": y, "left": x, "width": width, "height": height}
        sct_img = self.sct.grab(monitor)
        return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

    def get_monitor_info(self):
        return self.sct.monitors
