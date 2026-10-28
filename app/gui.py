
import tkinter as tk
from tkinter import ttk
import threading
import cv2
from scanner import scan_entire_list
from pynput import keyboard
from capture import capture_screen, configure_region
from ocr import recognize_text


class FollowBackApp:
    def on_global_key_press(self, key):
        if key == keyboard.Key.esc and self.is_scanning:
            self.stop_requested = True
    def __init__(self, root):
        self.root = root
        self.root.title("Do you follow me back?")
        self.root.geometry("620x650")
        self.root.minsize(520, 500)

        self.status = tk.StringVar(
            value="Configure your scan region to begin."
        )
        self.list_type = tk.StringVar(value="Following")

        self.scan_region = None
        self.is_ready = False
        self.is_configuring = False
        self.is_scanning = False
        self.stop_requested = False

        self._build_interface()
        self.esc_listener = keyboard.Listener(
            on_press=self.on_global_key_press
        )
        self.esc_listener.daemon = True
        self.esc_listener.start()
    def _build_interface(self):
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="FollowBack Checker",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            container,
            text="Read Instagram usernames from a selected screen region.",
            wraplength=540,
        ).pack(anchor="w", pady=(5, 15))

        ttk.Label(
            container,
            text="1. Select the list",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        choices = ttk.Frame(container)
        choices.pack(anchor="w", pady=6)

        for label in ("Followers", "Following"):
            ttk.Radiobutton(
                choices,
                text=label,
                variable=self.list_type,
                value=label,
                command=self.reset_ready,
            ).pack(side="left", padx=(0, 16))

        ttk.Label(
            container,
            text="2. Configure and scan",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(12, 5))

        ttk.Label(
            container,
            text=(
                "Open the selected Instagram list. Select the region "
                "containing the account rows. When scanning starts, "
                "switch to Instagram during the 3-second countdown."
            ),
            wraplength=540,
        ).pack(anchor="w")

        self.region_button = ttk.Button(
            container,
            text="Configure Scan Region",
            command=self.configure_region,
        )
        self.region_button.pack(anchor="w", pady=10)

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(0, 10))

        self.ready_button = ttk.Button(
            buttons,
            text="I'm Ready",
            command=self.mark_ready,
        )
        self.ready_button.pack(side="left")

        self.start_button = ttk.Button(
            buttons,
            text="Start OCR Test",
            command=self.start_scan,
        )
        self.start_button.pack(side="left", padx=8)

        self.stop_button = ttk.Button(
            buttons,
            text="Stop",
            command=self.stop_scan,
        )
        self.stop_button.pack(side="left")

        ttk.Separator(container).pack(fill="x", pady=8)

        ttk.Label(
            container,
            text="Status",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            container,
            textvariable=self.status,
            wraplength=540,
        ).pack(anchor="w", pady=(4, 10))

        ttk.Label(
            container,
            text="OCR Results",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        results_frame = ttk.Frame(container)
        results_frame.pack(fill="both", expand=True, pady=(6, 0))

        scrollbar = ttk.Scrollbar(results_frame)
        scrollbar.pack(side="right", fill="y")

        self.results = tk.Text(
            results_frame,
            height=10,
            wrap="word",
            font=("Consolas", 10),
            yscrollcommand=scrollbar.set,
        )
        self.results.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.results.yview)

        self.results.insert(
            "1.0",
            "OCR output will appear here after your first test.\n"
        )

    def reset_ready(self):
        self.is_ready = False
        self.status.set(
            f"Selected {self.list_type.get()}. "
            "Make sure the correct Instagram list is open."
        )

    def configure_region(self):
        if self.is_configuring or self.is_scanning:
            return

        self.is_configuring = True
        self.is_ready = False
        self.region_button.config(state="disabled")
        self.status.set(
            "Switch to Instagram. Selecting the region in 5 seconds..."
        )

        def worker():
            try:
                region = configure_region()
                self.root.after(
                    0, lambda: self.region_selected(region)
                )
            except Exception as error:
                message = str(error)
                self.root.after(
                    0, lambda: self.region_error(message)
                )

        threading.Thread(target=worker, daemon=True).start()

    def region_selected(self, region):
        self.is_configuring = False
        self.region_button.config(state="normal")

        if region is None:
            self.status.set("Region selection cancelled.")
            return

        self.scan_region = region
        self.status.set(
            f"Region saved: {region}. Click I'm Ready when prepared."
        )

    def region_error(self, message):
        self.is_configuring = False
        self.region_button.config(state="normal")
        self.status.set(f"Region setup failed: {message}")

    def mark_ready(self):
        if self.scan_region is None:
            self.status.set("Configure the scan region first.")
            return

        if self.is_scanning:
            return

        self.is_ready = True
        self.status.set(
            f"Ready to scan {self.list_type.get()}. "
            "Click Start OCR Test to capture one screen."
        )

    def start_scan(self):
        if self.is_scanning:
            return

        if self.scan_region is None:
            self.status.set("Configure the scan region first.")
            return

        if not self.is_ready:
            self.status.set("Click I'm Ready first.")
            return

        self.is_scanning = True
        self.stop_requested = False
        self.start_button.config(state="disabled")
        self.region_button.config(state="disabled")
        self.status.set(
            "Capturing in 3 seconds. Switch to Instagram now..."
        )

        threading.Thread(
            target=self.scan_worker,
            daemon=True,
        ).start()

    def scan_worker(self):
        try:
            import time

            for remaining in (3, 2, 1):
                if self.stop_requested:
                    self.root.after(
                        0,
                        lambda: self.finish_scan("Scan cancelled.")
                    )
                    return

                self.root.after(
                    0,
                    lambda n=remaining: self.status.set(
                        f"Starting in {n} seconds. Switch to Instagram!"
                    ),
                )
                time.sleep(1)

            if self.stop_requested:
                self.root.after(
                    0,
                    lambda: self.finish_scan("Scan cancelled.")
                )
                return

            candidates, cancelled, screens_scanned = scan_entire_list(
                self.scan_region,
                should_stop=lambda: self.stop_requested,
                progress_callback=lambda message: self.root.after(
                    0,
                    lambda m=message: self.status.set(m)
                ),
            )

            self.root.after(
                0,
                lambda: self.show_scan_results(
                    candidates,
                    cancelled,
                    screens_scanned,
                ),
            )

        except Exception as error:
            message = str(error)
            self.root.after(
                0,
                lambda: self.finish_scan(f"Scan failed: {message}")
            )

    def show_scan_results(self, candidates, cancelled, screens_scanned):
        self.results.delete("1.0", "end")

        self.results.insert(
            "end",
            f"Unique username candidates: {len(candidates)}\n"
            f"Screens scanned: {screens_scanned}\n"
            + "-" * 35 + "\n"
        )

        for username in candidates:
            self.results.insert("end", username + "\n")

        if not candidates:
            self.results.insert(
                "end",
                "No candidates detected. Check the selected region.\n"
            )

        if cancelled:
            message = (
                f"Scan cancelled. Kept {len(candidates)} candidates "
                f"from {screens_scanned} screens."
            )
        else:
            message = (
                f"Scan finished. Collected {len(candidates)} unique "
                f"candidates from {screens_scanned} screens."
            )

        self.finish_scan(message)

    def finish_scan(self, message):
        self.is_scanning = False
        self.start_button.config(state="normal")
        self.region_button.config(state="normal")
        self.status.set(message)

    def stop_scan(self):
        if self.is_scanning:
            self.stop_requested = True
            self.status.set("Stopping scan...")
        else:
            self.is_ready = False
            self.status.set("No scan is currently running.")


def run_app():
    root = tk.Tk()
    FollowBackApp(root)
    root.mainloop()


if __name__ == "__main__":
    run_app()
