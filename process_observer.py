import time, json, os, threading, mss, pytesseract, psutil
from datetime import datetime
from PIL import Image
from pynput import keyboard, mouse

class ProcessObserver:
    def __init__(self, output_file="workflow_traces.jsonl"):
        self.output_file = output_file
        self.is_running = False
        self.last_action_time = time.time()
        self.active_window_title = ""
        self.active_app_name = ""
        
        #buffer to accumulate recent user actions before writing a snapshot
        self.action_buffer = []

    def get_active_window_info(self):
        """Retrieves active window title and process name across platform OSs."""
        app_name = "Unknown"
        window_title = "Unknown"
        
        try:
            import pygetwindow as gw
            win = gw.getActiveWindow()
            if win:
                window_title = win.title
                #find process associated with active window
                for proc in psutil.process_iter(['pid', 'name']):
                    if proc.info['name'] and proc.info['name'].lower() in window_title.lower():
                        app_name = proc.info['name']
                        break
        except Exception:
            pass

        return app_name, window_title

    def capture_screen_text(self):
        """Captures active screen area and extracts visible text via OCR."""
        try:
            with mss.mss() as sct:
                #capture primary monitor
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                
                #convert raw pixels to PIL Image
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                
                #downscale image to speed up OCR inference
                img.thumbnail((1280, 720))
                
                #run OCR extraction
                extracted_text = pytesseract.image_to_string(img)
                #clean up whitespace
                clean_text = " ".join(extracted_text.split())
                return clean_text[:500]  # Store top 500 characters of contextual text
        except Exception as e:
            return f"[OCR Error: {e}]"

    def _on_click(self, x, y, button, pressed):
        if pressed and self.is_running:
            self.action_buffer.append({
                "type": "mouse_click",
                "button": str(button),
                "position": [x, y],
                "timestamp": datetime.now().isoformat()
            })

    def _on_press(self, key):
        if self.is_running:
            try:
                key_str = key.char
            except AttributeError:
                key_str = str(key)
                
            self.action_buffer.append({
                "type": "key_press",
                "key": key_str,
                "timestamp": datetime.now().isoformat()
            })

    def log_event_snapshot(self):
        """Bundles window state, input actions, and OCR context into a structured trace frame."""
        if not self.action_buffer:
            return #skip snapshot if user was idle

        app_name, window_title = self.get_active_window_info()
        ocr_context = self.capture_screen_text()

        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "app_name": app_name,
            "window_title": window_title,
            "actions_count": len(self.action_buffer),
            "recent_actions": self.action_buffer.copy(),
            "screen_ocr_summary": ocr_context
        }

        #clear buffer for next sampling interval
        self.action_buffer.clear()

        #write event snapshot to JSONL storage
        with open(self.output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot) + "\n")

        print(f" Recorded Trace Frame: App='{app_name}' | Title='{window_title}' | Actions={snapshot['actions_count']}")

    def start(self, poll_interval=5.0):
        self.is_running = True
        
        #start keyboard & mouse listeners in background threads
        self.mouse_listener = mouse.Listener(on_click=self._on_click)
        self.key_listener = keyboard.Listener(on_press=self._on_press)
        self.mouse_listener.start()
        self.key_listener.start()

        print(f"Observer Started. Sampling workflows every {poll_interval}s...")

        try:
            while self.is_running:
                time.sleep(poll_interval)
                self.log_event_snapshot()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.is_running = False
        if hasattr(self, 'mouse_listener'):
            self.mouse_listener.stop()
        if hasattr(self, 'key_listener'):
            self.key_listener.stop()
        print("Observer Stopped.")

if __name__ == "__main__":
    observer = ProcessObserver()
    observer.start(poll_interval=5.0)