import socket

class RetroArchClient:
    """
    Client for interacting with RetroArch via UDP Network Commands.
    Ensure 'Network Commands' is enabled in RetroArch (Settings -> Network -> Network Commands).
    Default port is 55355.
    """
    def __init__(self, host='127.0.0.1', port=55355):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)

    def pause_toggle(self):
        """Sends a PAUSE_TOGGLE command to RetroArch."""
        try:
            self.sock.sendto(b"PAUSE_TOGGLE\n", (self.host, self.port))
            print("DEBUG: Sent PAUSE_TOGGLE to RetroArch.")
            return True
        except Exception as e:
            print(f"RetroArch UDP Error: {e}")
            return False
