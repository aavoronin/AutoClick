from pathlib import Path
import pynput
import pyautogui
import cv2
import numpy as np
import time
import json
import sys
import threading
from PIL import ImageGrab  # Use PIL directly for screenshots (more reliable than pyautogui.screenshot)


class Recorder:
    """
    Records UI automation steps via keyboard & mouse.
    Toggle recording with NumLock. Generates a self-contained replay script.
    """

    def __init__(self, project_name: str, folder_name: str):
        self.project_name = project_name
        self.folder_name = folder_name
        self.base_dir = Path(folder_name)
        self.project_dir = self.base_dir / self.project_name
        self.project_dir.mkdir(parents=True, exist_ok=True)

        self.events = []
        self.image_counter = 0
        self.is_recording = False
        self._stop_event = threading.Event()
        self._listeners = []

        print(f"[Recorder] Project '{self.project_name}' initialized at {self.project_dir}")

    def _capture_region(self, x: int, y: int, dx: int = 50, dy: int = 20) -> str:
        """Captures a screen region centered at cursor: [x-dx, y-dy] to [x+dx, y+dy]."""
        try:
            screen_w, screen_h = pyautogui.size()
            left = max(0, x - dx)
            top = max(0, y - dy)
            width = min(2 * dx, screen_w - left)
            height = min(2 * dy, screen_h - top)

            if width <= 0 or height <= 0:
                print(f"[WARN] Invalid capture region at ({x},{y})")
                return ""

            # Small delay to let UI state settle before capture
            time.sleep(0.05)

            # Use PIL.ImageGrab directly - avoids pyscreeze dependency issues
            img = ImageGrab.grab(bbox=(left, top, left + width, top + height))

            self.image_counter += 1
            img_name = f"step_{self.image_counter:03d}.png"
            img_path = self.project_dir / img_name
            img.save(str(img_path), "PNG")
            return img_name
        except Exception as e:
            print(f"[ERROR] Failed to capture region: {e}")
            return ""

    def on_click(self, x: int, y: int, button, pressed: bool):
        try:
            if not self.is_recording or not pressed:
                return
            img_name = self._capture_region(x, y)
            if img_name:
                self.events.append(('click', img_name))
                print(f"[LOG] Mouse click captured -> {img_name}")
        except Exception as e:
            # Log but don't crash the listener
            print(f"[WARN] Error in on_click: {e}")

    def on_press(self, key):
        try:
            # Toggle recording on NumLock
            if key == pynput.keyboard.Key.num_lock:
                self.toggle_recording()
                return

            if not self.is_recording:
                return

            try:
                char = key.char
                if char and char.isprintable():
                    # Character keys are stored as typewrite strings
                    self.events.append(('type', char))
                    print(f"[LOG] Key typed: {repr(char)}")
                    return
            except AttributeError:
                pass

            # Non-character keys (Enter, PgUp, arrows, etc.) -> capture region at cursor
            x, y = pyautogui.position()
            img_name = self._capture_region(x, y)
            if img_name:
                self.events.append(('click', img_name))
                print(f"[LOG] Non-char key '{key.name}' captured as region -> {img_name}")
        except Exception as e:
            # Log but don't crash the listener
            print(f"[WARN] Error in on_press: {e}")

    def toggle_recording(self):
        self.is_recording = not self.is_recording
        if self.is_recording:
            print("\n[Recorder] ✅ Recording STARTED (NumLock ON)")
            print("[Recorder] Perform your actions. Press NumLock again to finish.\n")
            self.events.clear()
            self.image_counter = 0
        else:
            print("\n[Recorder] ⏹️ Recording STOPPED (NumLock OFF)")
            self.stop_listeners()
            self.generate_script()
            self._stop_event.set()

    def stop_listeners(self):
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass  # Ignore errors when stopping

    def record(self) -> None:
        print(f"[Recorder] Waiting for NumLock ON to start recording...")
        print("[Recorder] Press NumLock again to stop, generate code & save images.\n")

        kb_listener = pynput.keyboard.Listener(on_press=self.on_press)
        ms_listener = pynput.mouse.Listener(on_click=self.on_click)

        self._listeners = [kb_listener, ms_listener]
        for l in self._listeners:
            l.start()

        # Block until NumLock is pressed again
        self._stop_event.wait()
        print("[Recorder] Session finalized and resources cleaned up.")

    def generate_script(self):
        """Generates run_{project_name}.py with robust image-matching replay logic."""
        script_name = f"run_{self.project_name}.py"
        script_path = self.project_dir / script_name

        lines = [
            "import cv2",
            "import numpy as np",
            "import pyautogui",
            "import os",
            "import sys",
            "import time",
            "",
            "pyautogui.FAILSAFE = True  # Move mouse to top-left corner to force abort",
            "",
            "def click_if_detected(template_path, threshold=0.8):",
            "    \"\"\"",
            "    Detects template image on screen using similarity matching.",
            "    Clicks the center of the best match. Exits if not detected.",
            "    \"\"\"",
            "    if not os.path.exists(template_path):",
            "        print(f'[ERROR] Template not found: {template_path}')",
            "        sys.exit(1)",
            "",
            "    template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)",
            "    if template is None:",
            "        print(f'[ERROR] Failed to load template: {template_path}')",
            "        sys.exit(1)",
            "",
            "    h, w = template.shape[:2]",
            "    screenshot = pyautogui.screenshot()",
            "    screen_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)",
            "",
            "    # Find best matching area globally",
            "    result = cv2.matchTemplate(screen_cv, template, cv2.TM_CCOEFF_NORMED)",
            "    _, max_val, _, max_loc = cv2.minMaxLoc(result)",
            "",
            "    if max_val >= threshold:",
            "        cx = max_loc[0] + w // 2",
            "        cy = max_loc[1] + h // 2",
            "        pyautogui.click(cx, cy)",
            "        print(f'[LOG] Detected & clicked: {template_path} (confidence: {max_val:.3f})')",
            "        return True",
            "    else:",
            "        print(f'[ERROR] Target not detected in {template_path} (confidence: {max_val:.3f} < {threshold})')",
            "        sys.exit(1)",
            "",
            f"def run_{self.project_name}():",
            "    print('Starting replay...')",
            "    time.sleep(1)  # Delay to switch focus to target window",
        ]

        for evt_type, data in self.events:
            if evt_type == 'click':
                # Use relative path; script expects images in the same directory
                lines.append(f"    click_if_detected('{data}')")
                lines.append("    time.sleep(0.3)")
            elif evt_type == 'type':
                # json.dumps properly escapes quotes, slashes, newlines, etc.
                safe_str = json.dumps(data)
                lines.append(f"    pyautogui.typewrite({safe_str})")
                lines.append("    time.sleep(0.05)")

        lines.append("    print('✅ Replay completed successfully.')")
        lines.append("")
        lines.append("if __name__ == '__main__':")
        lines.append(f"    run_{self.project_name}()")

        script_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n[Recorder] 📄 Replay script saved to: {script_path}")
        print(f"[Recorder] 🖼️ {self.image_counter} template images saved in: {self.project_dir}")