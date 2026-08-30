import ctypes
import time
import threading
from PyQt6.QtCore import QObject, pyqtSignal

# Standard Windows Virtual Keys
VK_NAMES = {
    0x01: 'LMouse', 0x02: 'RMouse', 0x04: 'MMouse', 0x05: 'Mouse4', 0x06: 'Mouse5',
    0x08: 'Backspace', 0x09: 'Tab', 0x0D: 'Enter', 0x10: 'Shift', 0x11: 'Ctrl',
    0x12: 'Alt', 0x13: 'Pause', 0x14: 'CapsLock', 0x1B: 'Esc', 0x20: 'Space',
    0x21: 'PageUp', 0x22: 'PageDown', 0x23: 'End', 0x24: 'Home',
    0x25: 'Left', 0x26: 'Up', 0x27: 'Right', 0x28: 'Down',
    0x2C: 'PrintScreen', 0x2D: 'Insert', 0x2E: 'Delete',
    0x5B: 'LWin', 0x5C: 'RWin',
    # Numpad
    0x60: 'Num0', 0x61: 'Num1', 0x62: 'Num2', 0x63: 'Num3', 0x64: 'Num4',
    0x65: 'Num5', 0x66: 'Num6', 0x67: 'Num7', 0x68: 'Num8', 0x69: 'Num9',
    0x6A: 'Num*', 0x6B: 'Num+', 0x6D: 'Num-', 0x6E: 'Num.', 0x6F: 'Num/',
    # F-keys
    0x70: 'F1', 0x71: 'F2', 0x72: 'F3', 0x73: 'F4', 0x74: 'F5', 0x75: 'F6',
    0x76: 'F7', 0x77: 'F8', 0x78: 'F9', 0x79: 'F10', 0x7A: 'F11', 0x7B: 'F12',
}
# Add A-Z and 0-9
for i in range(0x30, 0x3A): VK_NAMES[i] = chr(i)
for i in range(0x41, 0x5B): VK_NAMES[i] = chr(i)

# XInput Gamepad Buttons
XINPUT_BUTTONS = {
    0x0001: 'Pad_Up', 0x0002: 'Pad_Down', 0x0004: 'Pad_Left', 0x0008: 'Pad_Right',
    0x0010: 'Pad_Start', 0x0020: 'Pad_Back', 0x0040: 'Pad_L3', 0x0080: 'Pad_R3',
    0x0100: 'Pad_LB', 0x0200: 'Pad_RB', 0x1000: 'Pad_A', 0x2000: 'Pad_B',
    0x4000: 'Pad_X', 0x8000: 'Pad_Y',
}

class XINPUT_STATE(ctypes.Structure):
    class _GAMEPAD(ctypes.Structure):
        _fields_ = [
            ("wButtons", ctypes.c_ushort),
            ("bLeftTrigger", ctypes.c_ubyte),
            ("bRightTrigger", ctypes.c_ubyte),
            ("sThumbLX", ctypes.c_short),
            ("sThumbLY", ctypes.c_short),
            ("sThumbRX", ctypes.c_short),
            ("sThumbRY", ctypes.c_short),
        ]
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _GAMEPAD)]

class HotkeyManager(QObject):
    hotkey_triggered = pyqtSignal(str) # Emits the action name

    def __init__(self):
        super().__init__()
        self.bindings = {} # action_name -> list of keys
        self.running = True
        self.user32 = ctypes.windll.user32
        
        try:
            self.xinput = ctypes.windll.xinput1_4
        except OSError:
            try:
                self.xinput = ctypes.windll.xinput1_3
            except OSError:
                self.xinput = None

        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        
        # State tracking to avoid rapid re-triggering
        self._action_states = {} 

    def set_binding(self, action_name, keys):
        """keys is a list of strings, e.g. ['Ctrl', 'F1'] or ['Pad_RB', 'Pad_A']"""
        self.bindings[action_name] = keys
        self._action_states[action_name] = False

    def get_binding(self, action_name):
        return self.bindings.get(action_name, [])

    def _poll_loop(self):
        while self.running:
            time.sleep(0.016) # ~60Hz
            
            # Read current states
            pressed_vks = set()
            for vk, name in VK_NAMES.items():
                if self.user32.GetAsyncKeyState(vk) & 0x8000:
                    pressed_vks.add(name)
                    
            pressed_pads = set()
            if self.xinput:
                for i in range(4): # 4 controllers max
                    state = XINPUT_STATE()
                    res = self.xinput.XInputGetState(i, ctypes.byref(state))
                    if res == 0: # ERROR_SUCCESS
                        buttons = state.Gamepad.wButtons
                        for mask, name in XINPUT_BUTTONS.items():
                            if buttons & mask:
                                pressed_pads.add(name)
            
            all_pressed = pressed_vks.union(pressed_pads)
            
            for action, required_keys in self.bindings.items():
                if not required_keys:
                    continue
                    
                # Check if ALL required keys are currently pressed
                is_active = all(k in all_pressed for k in required_keys)
                
                was_active = self._action_states.get(action, False)
                
                if is_active and not was_active:
                    self.hotkey_triggered.emit(action)
                    self._action_states[action] = True
                elif not is_active and was_active:
                    self._action_states[action] = False

    def stop(self):
        self.running = False
