"""
Retro Terminal GUI for Audit Supervisor
- Green monochrome CRT-style display
- Big red octagon emergency stop button
- Message input to guide agents
- Scrolling agent messages
"""

import asyncio
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import math


# ==============================================================================
# COLOR SCHEMES
# ==============================================================================

COLORS = {
    # CRT Green Monochrome
    "bg_dark": "#0a0a0a",
    "bg_monitor": "#001100",
    "green_dim": "#003300",
    "green_normal": "#00aa00",
    "green_bright": "#00ff00",
    "green_glow": "#33ff33",

    # Terminal chrome
    "chrome_dark": "#1a1a1a",
    "chrome_mid": "#2a2a2a",
    "chrome_light": "#3a3a3a",

    # Emergency stop
    "red_dark": "#660000",
    "red_normal": "#cc0000",
    "red_bright": "#ff0000",
    "red_glow": "#ff3333",

    # Status indicators
    "amber": "#ffaa00",
    "blue": "#0066cc",
}


# ==============================================================================
# OCTAGON BUTTON (Emergency Stop)
# ==============================================================================

class OctagonButton(tk.Canvas):
    """
    Big red octagonal emergency stop button.
    Because every good control panel needs one.
    """

    def __init__(self, parent, size: int = 120, command: Optional[Callable] = None, **kwargs):
        super().__init__(
            parent,
            width=size,
            height=size,
            bg=COLORS["chrome_dark"],
            highlightthickness=0,
            **kwargs
        )
        self.size = size
        self.command = command
        self.is_pressed = False
        self.is_stopped = False

        self._draw_button()
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _get_octagon_points(self, cx: int, cy: int, radius: int) -> List[int]:
        """Calculate octagon vertices."""
        points = []
        for i in range(8):
            angle = math.pi / 8 + i * math.pi / 4  # Start rotated for flat top
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            points.extend([x, y])
        return points

    def _draw_button(self):
        """Draw the octagonal stop button."""
        self.delete("all")

        cx, cy = self.size // 2, self.size // 2
        outer_r = self.size // 2 - 5
        inner_r = outer_r - 8

        # Outer ring (dark border)
        outer_points = self._get_octagon_points(cx, cy, outer_r)
        self.create_polygon(
            outer_points,
            fill=COLORS["chrome_light"],
            outline=COLORS["chrome_mid"],
            width=2,
            tags="outer"
        )

        # Main button face
        color = COLORS["red_bright"] if self.is_pressed else COLORS["red_normal"]
        if self.is_stopped:
            color = COLORS["red_dark"]

        inner_points = self._get_octagon_points(cx, cy, inner_r)
        self.create_polygon(
            inner_points,
            fill=color,
            outline=COLORS["red_dark"],
            width=2,
            tags="face"
        )

        # STOP text
        text_color = "#ffffff" if not self.is_stopped else "#666666"
        self.create_text(
            cx, cy,
            text="STOP",
            font=("Courier", 14, "bold"),
            fill=text_color,
            tags="text"
        )

        # Glow effect when pressed
        if self.is_pressed and not self.is_stopped:
            glow_points = self._get_octagon_points(cx, cy, outer_r + 3)
            self.create_polygon(
                glow_points,
                fill="",
                outline=COLORS["red_glow"],
                width=2,
                tags="glow"
            )

    def _on_press(self, event):
        if not self.is_stopped:
            self.is_pressed = True
            self._draw_button()

    def _on_release(self, event):
        if self.is_pressed and not self.is_stopped:
            self.is_pressed = False
            self.is_stopped = True
            self._draw_button()
            if self.command:
                self.command()

    def _on_enter(self, event):
        if not self.is_stopped:
            self.config(cursor="hand2")

    def _on_leave(self, event):
        self.config(cursor="")

    def reset(self):
        """Reset the button to active state."""
        self.is_stopped = False
        self.is_pressed = False
        self._draw_button()


# ==============================================================================
# CRT MONITOR DISPLAY
# ==============================================================================

class CRTMonitor(tk.Frame):
    """
    CRT-style monitor with green phosphor text.
    Includes scanline effect and text glow.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=COLORS["chrome_dark"], **kwargs)

        # Monitor bezel
        self.bezel = tk.Frame(self, bg=COLORS["chrome_mid"], padx=15, pady=15)
        self.bezel.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Inner bezel (rounded corners effect)
        self.inner_bezel = tk.Frame(self.bezel, bg=COLORS["chrome_dark"], padx=5, pady=5)
        self.inner_bezel.pack(fill=tk.BOTH, expand=True)

        # Screen frame
        self.screen_frame = tk.Frame(self.inner_bezel, bg=COLORS["bg_monitor"])
        self.screen_frame.pack(fill=tk.BOTH, expand=True)

        # Create monospace font
        self.mono_font = tkfont.Font(family="Courier", size=10, weight="normal")
        self.mono_font_bold = tkfont.Font(family="Courier", size=10, weight="bold")

        # Text widget for scrolling output
        self.text = tk.Text(
            self.screen_frame,
            bg=COLORS["bg_monitor"],
            fg=COLORS["green_normal"],
            insertbackground=COLORS["green_bright"],
            font=self.mono_font,
            wrap=tk.WORD,
            state=tk.DISABLED,
            cursor="arrow",
            padx=10,
            pady=10,
            relief=tk.FLAT,
            highlightthickness=0,
        )
        self.text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        # Scrollbar (styled)
        self.scrollbar = tk.Scrollbar(
            self.screen_frame,
            command=self.text.yview,
            bg=COLORS["chrome_dark"],
            troughcolor=COLORS["bg_monitor"],
            activebackground=COLORS["green_dim"],
        )
        self.scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        self.text.config(yscrollcommand=self.scrollbar.set)

        # Configure text tags for different message types
        self.text.tag_configure("normal", foreground=COLORS["green_normal"])
        self.text.tag_configure("bright", foreground=COLORS["green_bright"])
        self.text.tag_configure("dim", foreground=COLORS["green_dim"])
        self.text.tag_configure("header", foreground=COLORS["green_glow"], font=self.mono_font_bold)
        self.text.tag_configure("error", foreground=COLORS["red_bright"])
        self.text.tag_configure("warning", foreground=COLORS["amber"])
        self.text.tag_configure("info", foreground=COLORS["blue"])
        self.text.tag_configure("input", foreground=COLORS["green_glow"])

        # Add scanline overlay effect (simulated with tag)
        self.text.tag_configure("scanline", background="#001500")

    def write(self, text: str, tag: str = "normal", newline: bool = True):
        """Write text to the monitor."""
        self.text.config(state=tk.NORMAL)
        if newline and not text.endswith("\n"):
            text += "\n"
        self.text.insert(tk.END, text, tag)
        self.text.see(tk.END)
        self.text.config(state=tk.DISABLED)

    def write_header(self, text: str):
        """Write a header line."""
        self.write("=" * 60, "dim")
        self.write(f" {text} ".center(60, "="), "header")
        self.write("=" * 60, "dim")

    def write_agent(self, agent_id: str, message: str):
        """Write a message from an agent."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.write(f"[{timestamp}] ", "dim", newline=False)
        self.write(f"[{agent_id}] ", "bright", newline=False)
        self.write(message, "normal")

    def write_system(self, message: str):
        """Write a system message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.write(f"[{timestamp}] ", "dim", newline=False)
        self.write(f"[SYSTEM] ", "warning", newline=False)
        self.write(message, "normal")

    def write_error(self, message: str):
        """Write an error message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.write(f"[{timestamp}] ", "dim", newline=False)
        self.write(f"[ERROR] ", "error", newline=False)
        self.write(message, "error")

    def write_user_input(self, message: str):
        """Write user input (echo)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.write(f"[{timestamp}] ", "dim", newline=False)
        self.write(f"[YOU] > ", "input", newline=False)
        self.write(message, "input")

    def clear(self):
        """Clear the monitor."""
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.config(state=tk.DISABLED)


# ==============================================================================
# INPUT PANEL (Keyboard area)
# ==============================================================================

class InputPanel(tk.Frame):
    """
    Input panel styled like a keyboard area.
    Text entry with send button.
    """

    def __init__(self, parent, on_send: Optional[Callable[[str], None]] = None, **kwargs):
        super().__init__(parent, bg=COLORS["chrome_dark"], **kwargs)
        self.on_send = on_send

        # Create input frame
        self.input_frame = tk.Frame(self, bg=COLORS["chrome_mid"], padx=10, pady=10)
        self.input_frame.pack(fill=tk.X, padx=10, pady=10)

        # Label
        self.label = tk.Label(
            self.input_frame,
            text="OPERATOR INPUT >",
            font=("Courier", 10, "bold"),
            fg=COLORS["green_bright"],
            bg=COLORS["chrome_mid"],
        )
        self.label.pack(side=tk.LEFT, padx=(0, 10))

        # Entry widget
        self.entry = tk.Entry(
            self.input_frame,
            font=("Courier", 11),
            bg=COLORS["bg_monitor"],
            fg=COLORS["green_bright"],
            insertbackground=COLORS["green_bright"],
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=COLORS["green_dim"],
            highlightcolor=COLORS["green_normal"],
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.entry.bind("<Return>", self._on_enter)

        # Send button
        self.send_btn = tk.Button(
            self.input_frame,
            text="SEND",
            font=("Courier", 10, "bold"),
            bg=COLORS["green_dim"],
            fg=COLORS["green_bright"],
            activebackground=COLORS["green_normal"],
            activeforeground=COLORS["bg_dark"],
            relief=tk.RAISED,
            borderwidth=2,
            command=self._send,
        )
        self.send_btn.pack(side=tk.LEFT)

    def _on_enter(self, event):
        self._send()

    def _send(self):
        text = self.entry.get().strip()
        if text:
            self.entry.delete(0, tk.END)
            if self.on_send:
                self.on_send(text)

    def set_enabled(self, enabled: bool):
        """Enable or disable input."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.entry.config(state=state)
        self.send_btn.config(state=state)


# ==============================================================================
# STATUS BAR
# ==============================================================================

class StatusBar(tk.Frame):
    """Status bar with indicators."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=COLORS["chrome_dark"], **kwargs)

        # Phase indicator
        self.phase_label = tk.Label(
            self,
            text="PHASE: IDLE",
            font=("Courier", 9),
            fg=COLORS["green_normal"],
            bg=COLORS["chrome_dark"],
        )
        self.phase_label.pack(side=tk.LEFT, padx=10)

        # Agent count
        self.agent_label = tk.Label(
            self,
            text="AGENTS: 0/0",
            font=("Courier", 9),
            fg=COLORS["green_normal"],
            bg=COLORS["chrome_dark"],
        )
        self.agent_label.pack(side=tk.LEFT, padx=10)

        # Health indicator
        self.health_label = tk.Label(
            self,
            text="[OK] HEALTHY",
            font=("Courier", 9, "bold"),
            fg=COLORS["green_bright"],
            bg=COLORS["chrome_dark"],
        )
        self.health_label.pack(side=tk.RIGHT, padx=10)

        # Time
        self.time_label = tk.Label(
            self,
            text="00:00:00",
            font=("Courier", 9),
            fg=COLORS["green_dim"],
            bg=COLORS["chrome_dark"],
        )
        self.time_label.pack(side=tk.RIGHT, padx=10)

    def set_phase(self, phase: str):
        self.phase_label.config(text=f"PHASE: {phase.upper()}")

    def set_agents(self, completed: int, total: int):
        self.agent_label.config(text=f"AGENTS: {completed}/{total}")

    def set_health(self, status: str):
        colors = {
            "healthy": (COLORS["green_bright"], "[OK]"),
            "degraded": (COLORS["amber"], "[!!]"),
            "critical": (COLORS["red_bright"], "[XX]"),
        }
        color, indicator = colors.get(status.lower(), (COLORS["green_normal"], "[??]"))
        self.health_label.config(text=f"{indicator} {status.upper()}", fg=color)

    def update_time(self, elapsed_seconds: int):
        hours = elapsed_seconds // 3600
        minutes = (elapsed_seconds % 3600) // 60
        seconds = elapsed_seconds % 60
        self.time_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")


# ==============================================================================
# MAIN RETRO TERMINAL WINDOW
# ==============================================================================

class RetroTerminalGUI:
    """
    Main retro terminal GUI window.
    Combines all components into a control panel interface.
    """

    def __init__(
        self,
        on_stop: Optional[Callable] = None,
        on_user_input: Optional[Callable[[str], None]] = None,
    ):
        self.on_stop = on_stop
        self.on_user_input = on_user_input
        self._message_queue: queue.Queue = queue.Queue()
        self._is_running = False
        self._start_time: Optional[datetime] = None

        # Create main window
        self.root = tk.Tk()
        self.root.title("AUDIT SUPERVISOR CONTROL TERMINAL")
        self.root.geometry("900x700")
        self.root.configure(bg=COLORS["chrome_dark"])
        self.root.minsize(800, 600)

        # Prevent window close (use stop button)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_attempt)

        self._create_layout()
        self._start_time_update()

    def _create_layout(self):
        """Create the GUI layout."""
        # Title bar
        title_frame = tk.Frame(self.root, bg=COLORS["chrome_mid"], height=40)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        title_label = tk.Label(
            title_frame,
            text=">>> FAST_SWARM AUDIT SUPERVISOR CONTROL TERMINAL <<<",
            font=("Courier", 12, "bold"),
            fg=COLORS["green_glow"],
            bg=COLORS["chrome_mid"],
        )
        title_label.pack(expand=True)

        # Main content frame
        content_frame = tk.Frame(self.root, bg=COLORS["chrome_dark"])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left panel: Monitor
        monitor_frame = tk.Frame(content_frame, bg=COLORS["chrome_dark"])
        monitor_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.monitor = CRTMonitor(monitor_frame)
        self.monitor.pack(fill=tk.BOTH, expand=True)

        # Right panel: Controls
        control_frame = tk.Frame(content_frame, bg=COLORS["chrome_dark"], width=180)
        control_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        control_frame.pack_propagate(False)

        # Emergency stop button
        stop_label = tk.Label(
            control_frame,
            text="EMERGENCY",
            font=("Courier", 10, "bold"),
            fg=COLORS["red_bright"],
            bg=COLORS["chrome_dark"],
        )
        stop_label.pack(pady=(20, 5))

        self.stop_button = OctagonButton(
            control_frame,
            size=140,
            command=self._on_stop_pressed,
        )
        self.stop_button.pack(pady=10)

        # Status indicators
        indicator_frame = tk.Frame(control_frame, bg=COLORS["chrome_dark"])
        indicator_frame.pack(fill=tk.X, pady=20)

        # LED-style indicators
        self._create_led(indicator_frame, "PWR", COLORS["green_bright"])
        self._create_led(indicator_frame, "RUN", COLORS["amber"])
        self._create_led(indicator_frame, "ERR", COLORS["chrome_mid"])

        # Input panel (bottom)
        self.input_panel = InputPanel(self.root, on_send=self._on_user_send)
        self.input_panel.pack(fill=tk.X, side=tk.BOTTOM)

        # Status bar
        self.status_bar = StatusBar(self.root)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # Initial message
        self.monitor.write_header("SYSTEM INITIALIZED")
        self.monitor.write_system("Audit Supervisor Control Terminal ready.")
        self.monitor.write_system("Press START to begin audit or type commands below.")
        self.monitor.write("")

    def _create_led(self, parent, label: str, color: str):
        """Create an LED-style indicator."""
        frame = tk.Frame(parent, bg=COLORS["chrome_dark"])
        frame.pack(fill=tk.X, pady=2)

        # LED "bulb"
        canvas = tk.Canvas(frame, width=16, height=16, bg=COLORS["chrome_dark"], highlightthickness=0)
        canvas.pack(side=tk.LEFT, padx=5)
        canvas.create_oval(2, 2, 14, 14, fill=color, outline=COLORS["chrome_light"])

        # Label
        lbl = tk.Label(
            frame,
            text=label,
            font=("Courier", 9),
            fg=COLORS["green_normal"],
            bg=COLORS["chrome_dark"],
        )
        lbl.pack(side=tk.LEFT)

    def _on_stop_pressed(self):
        """Handle emergency stop button press."""
        self.monitor.write_error("!!! EMERGENCY STOP ACTIVATED !!!")
        self.monitor.write_system("Sending stop signal to all agents...")
        if self.on_stop:
            self.on_stop()

    def _on_user_send(self, text: str):
        """Handle user input."""
        self.monitor.write_user_input(text)
        if self.on_user_input:
            self.on_user_input(text)

    def _on_close_attempt(self):
        """Handle window close attempt."""
        self.monitor.write_warning("Use EMERGENCY STOP to halt operations.")

    def _start_time_update(self):
        """Start the time update loop."""
        self._update_time()

    def _update_time(self):
        """Update elapsed time display."""
        if self._start_time:
            elapsed = int((datetime.now() - self._start_time).total_seconds())
            self.status_bar.update_time(elapsed)
        self.root.after(1000, self._update_time)

    # ==========================================================================
    # PUBLIC API
    # ==========================================================================

    def start(self):
        """Start the GUI main loop (blocking)."""
        self._is_running = True
        self._start_time = datetime.now()
        self.root.mainloop()

    def start_async(self):
        """Start the GUI in a separate thread (non-blocking)."""
        self._is_running = True
        self._start_time = datetime.now()
        self._gui_thread = threading.Thread(target=self.root.mainloop, daemon=True)
        self._gui_thread.start()

    def stop(self):
        """Stop the GUI."""
        self._is_running = False
        self.root.quit()

    def write(self, text: str, tag: str = "normal"):
        """Write text to the monitor (thread-safe)."""
        self._message_queue.put(("write", text, tag))
        self.root.after(0, self._process_queue)

    def write_agent(self, agent_id: str, message: str):
        """Write agent message (thread-safe)."""
        self._message_queue.put(("agent", agent_id, message))
        self.root.after(0, self._process_queue)

    def write_system(self, message: str):
        """Write system message (thread-safe)."""
        self._message_queue.put(("system", message, None))
        self.root.after(0, self._process_queue)

    def write_error(self, message: str):
        """Write error message (thread-safe)."""
        self._message_queue.put(("error", message, None))
        self.root.after(0, self._process_queue)

    def write_header(self, text: str):
        """Write header (thread-safe)."""
        self._message_queue.put(("header", text, None))
        self.root.after(0, self._process_queue)

    def set_phase(self, phase: str):
        """Set current phase display."""
        self.root.after(0, lambda: self.status_bar.set_phase(phase))

    def set_agents(self, completed: int, total: int):
        """Set agent count display."""
        self.root.after(0, lambda: self.status_bar.set_agents(completed, total))

    def set_health(self, status: str):
        """Set health status display."""
        self.root.after(0, lambda: self.status_bar.set_health(status))

    def ask_question(self, question: str, callback: Callable[[str], None]):
        """Ask the user a question and get response via input."""
        self.monitor.write("")
        self.monitor.write("=" * 50, "warning")
        self.monitor.write(f"QUESTION: {question}", "warning")
        self.monitor.write("=" * 50, "warning")
        self.monitor.write("Please type your response below and press SEND.", "dim")
        # Store callback for next input
        self._pending_callback = callback

    def _process_queue(self):
        """Process messages from the queue."""
        try:
            while True:
                msg_type, arg1, arg2 = self._message_queue.get_nowait()
                if msg_type == "write":
                    self.monitor.write(arg1, arg2 or "normal")
                elif msg_type == "agent":
                    self.monitor.write_agent(arg1, arg2)
                elif msg_type == "system":
                    self.monitor.write_system(arg1)
                elif msg_type == "error":
                    self.monitor.write_error(arg1)
                elif msg_type == "header":
                    self.monitor.write_header(arg1)
        except queue.Empty:
            pass

    def reset_stop_button(self):
        """Reset the emergency stop button."""
        self.stop_button.reset()


# ==============================================================================
# DEMO / TEST
# ==============================================================================

def demo():
    """Demo the GUI."""
    import random

    def on_stop():
        print("STOP PRESSED!")

    def on_input(text):
        print(f"User input: {text}")
        gui.write_system(f"Received: {text}")

    gui = RetroTerminalGUI(on_stop=on_stop, on_user_input=on_input)

    # Simulate some messages
    def simulate():
        agents = ["1A", "1B", "1C", "2A", "2B"]
        messages = [
            "Scanning files...",
            "Found 23 Python files",
            "Analyzing dependencies",
            "Processing Models/",
            "Dead code candidate found",
            "Reviewing Services/",
            "Test coverage: 67%",
        ]

        gui.write_header("AUDIT STARTED")
        gui.set_phase("Section Review")
        gui.set_agents(0, 8)

        count = 0
        def add_message():
            nonlocal count
            if count < 20:
                agent = random.choice(agents)
                msg = random.choice(messages)
                gui.write_agent(agent, msg)
                count += 1
                gui.set_agents(count // 4, 8)
                gui.root.after(500, add_message)

        gui.root.after(1000, add_message)

    gui.root.after(100, simulate)
    gui.start()


if __name__ == "__main__":
    demo()
