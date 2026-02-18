"""
qt_window_manager.py  -  drop-in replacement for chromium_manager.py

Uses PySide6 + PySide6-WebEngine (bundled Chromium) so no system Chrome is
required on any platform.  The public interface is identical to ChromiumManager:

    chromium_manager.launch_all_windows(iniconfig)
    chromium_manager.wait_for_exit()
    chromium_manager.terminate_all()
    chromium_manager.get_process(window_name)  -> returns None (no subprocess)
    chromium_manager.is_running                -> bool

Install deps:
    pip install PySide6 screeninfo
    (PySide6 bundles WebEngine - no separate package needed)
"""

from __future__ import annotations

import sys
import time
import threading
import urllib.request
import urllib.error
import queue

from typing import Optional


from PySide6.QtCore import Qt, QUrl, QTimer, Signal, QObject  
from PySide6.QtGui import QDesktopServices, QAction
from PySide6.QtWidgets import QApplication, QMenu, QDialog, QVBoxLayout, QFileDialog 
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage, QWebEngineContextMenuRequest

try:
    from screeninfo import get_monitors
except ImportError:
    get_monitors = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_server(url: str, timeout: float = 15.0, interval: float = 0.25) -> bool:
    """Poll url until the HTTP server responds or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except urllib.error.HTTPError:
            # Server is up but returned an HTTP error — still alive
            return True
        except Exception:
            time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# QWebEnginePage subclass — JS console forwarding
# ---------------------------------------------------------------------------

class _DebugPage(QWebEnginePage):
    """Forwards JS console output to Python stdout for debugging."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self._name = name

    def javaScriptConsoleMessage(self, level, message, line, source):
        level_str = {
            QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel:    "INFO",
            QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "WARN",
            QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:   "ERROR",
        }.get(level, "LOG")
        print(f"[JS:{self._name}] {level_str} {source}:{line} - {message}")


# ---------------------------------------------------------------------------
# Individual fullscreen window
# ---------------------------------------------------------------------------

class _VPinWindow(QWebEngineView):
    def __init__(
        self,
        name: str,
        url: str,
        x: int,
        y: int,
        width: int,
        height: int,
        manager_ui_port: int = 8001,
    ):
        super().__init__()
        self.name = name
        self._url = url
        self.manager_ui_port = manager_ui_port

        self.setPage(_DebugPage(name, self))

        # contextMenuRequested is a signal on QWebEngineView
        from PySide6.QtCore import Qt  # Ensure Qt is imported

        # 1. Tell Qt we want to handle the menu ourselves
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # 2. Connect the correct signal
        self.customContextMenuRequested.connect(self._show_context_menu)

        # Enable everything the themes need, matching original chromium_manager flags
        s = self.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)

        self.setWindowTitle(f"VPinFE - {name}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet("background: black;")
        self.setGeometry(x, y, width, height)
        self.showFullScreen()

    def load_url(self):
        print(f"[QtWindowManager] Loading '{self.name}': {self._url}")
        self.load(QUrl(self._url))

    def closeEvent(self, event):
        print(f"[QtWindowManager] Window '{self.name}' closed.")
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, point):
        """Creates a right-click menu to control the app."""
        menu = QMenu(self)

        # ---------------------------------------------------------
        # 1. FIX THE "BLACK BOX" STYLE
        # Force the menu to use standard colors regardless of macOS Dark Mode
        # ---------------------------------------------------------
        menu.setStyleSheet("""
            QMenu {
                background-color: #F0F0F0; /* Light Grey Background */
                color: black;              /* Black Text */
                border: 1px solid #999999;
                padding: 4px;
            }
            QMenu::item {
                padding: 4px 24px;
                background-color: transparent;
            }
            QMenu::item:selected { 
                background-color: #0078D7; /* Blue Highlight */
                color: white;              /* White Text on Highlight */
            }
        """)

        # ---------------------------------------------------------
        # 2. DEFINE ACTIONS
        # ---------------------------------------------------------
        
        # Action: Reload
        reload_action = menu.addAction("Reload Window")
        reload_action.triggered.connect(self.reload)

        # Action: Open Manager
        manager_action = menu.addAction("Open Manager")
        # Now calls our internal modal dialog method
        manager_action.triggered.connect(self._open_manager)

        menu.addSeparator()

        # Action: Quit
        quit_action = menu.addAction("Quit VPinFE")
        # Connect to the global app quit slot
        quit_action.triggered.connect(QApplication.instance().quit)

        # ---------------------------------------------------------
        # 3. SHOW MENU
        # ---------------------------------------------------------
        # Map local widget coordinates to global screen coordinates
        global_point = self.mapToGlobal(point)
        menu.exec(global_point)
        
    def closeEvent(self, event):
        print(f"[Qt] Closing window: {self.name}")
        event.accept()  # Crucial: Tells Qt to proceed with closing
        
    def _show_manager_context_menu(self, point):
        """Show a context menu for the Manager Popup."""
        menu = QMenu(self._manager_view)

        # 1. Apply the same clean style (Light Grey)
        menu.setStyleSheet("""
            QMenu {
                background-color: #F0F0F0;
                color: black;
                border: 1px solid #999999;
                padding: 4px;
            }
            QMenu::item {
                padding: 4px 24px;
                background-color: transparent;
            }
            QMenu::item:selected { 
                background-color: #B00020; /* Red for Close */
                color: white;
            }
        """)

        # 2. Add 'Close' Action
        close_action = menu.addAction("Close Manager")
        close_action.triggered.connect(self._manager_dialog.close)
        
        # 3. Add 'Reload' (Just in case it gets stuck)
        reload_action = menu.addAction("Reload Page")
        reload_action.triggered.connect(self._manager_view.reload)

        # 4. Show Menu
        global_point = self._manager_view.mapToGlobal(point)
        menu.exec(global_point)
        
    def _open_manager(self):
        """Opens the Manager UI in a modal overlay window."""
        # 1. Prevent opening multiple manager windows
        if hasattr(self, '_manager_dialog') and self._manager_dialog.isVisible():
            self._manager_dialog.raise_()
            self._manager_dialog.activateWindow()
            return

        # 2. Create the dialog with 'self' as parent (keeps it on top)
        self._manager_dialog = QDialog(self)
        self._manager_dialog.setWindowTitle("VPinFE Manager")
        self._manager_dialog.resize(int(self.width() * 0.8), int(self.height() * 0.8))

        # Force ESC key to work even if browser has focus
        self._manager_dialog.setFocusPolicy(Qt.StrongFocus)
        
        # 3. CRITICAL: Use WindowModal
        # This blocks input to the game window (Modal)
        # BUT allows Python background threads to keep running
        self._manager_dialog.setWindowModality(Qt.WindowModality.WindowModal)

        # 4. Create Layout
        layout = QVBoxLayout(self._manager_dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 5. Create View (Keep a reference with 'self')
        self._manager_view = QWebEngineView()
        self._manager_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._manager_view.customContextMenuRequested.connect(self._show_manager_context_menu)
        
        # --- REMOVED THE DEBUG SETTING THAT CAUSED THE CRASH ---
        # If we need this later, we can enable it via command line flags instead.
        
        # Debug: Print when the page actually loads
        def on_load_finished(ok):
            status = "SUCCESS" if ok else "FAILED"
            print(f"[Qt] Manager UI Load finished: {status}")
            
        self._manager_view.loadFinished.connect(on_load_finished)

        # 6. Load URL
        url_str = f"http://localhost:{self.manager_ui_port}"
        print(f"[Qt] Opening Manager: {url_str}")
        self._manager_view.setUrl(QUrl(url_str))
        
        # 7. Add to layout and Show
        layout.addWidget(self._manager_view)
        
        # Use show() instead of exec() to prevent freezing the server
        self._manager_dialog.show()
        

    def _return_home(self):
        """Mirrors splash.html: calls get_theme_index_page and navigates there."""
        print("[QtWindowManager] Returning home via get_theme_index_page...")
        self.page().runJavaScript(
            "window.vpin.call('get_theme_index_page')"
            ".then(function(loc) { window.location = loc; })"
            ".catch(function(e) { console.error('Return home failed:', e); })"
        )


# ---------------------------------------------------------------------------
# Manager - drop-in replacement for ChromiumManager
# ---------------------------------------------------------------------------

class QtWindowManager:
    """
    Drop-in replacement for ChromiumManager.
    Launches embedded PySide6/QtWebEngine (Chromium) windows instead of
    spawning a system Chrome process.
    """

    def __init__(self):
        self._app: Optional[QApplication] = None
        self._windows: list[_VPinWindow] = []
        self._exit_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API - matches ChromiumManager exactly
    # ------------------------------------------------------------------

    def launch_all_windows(self, iniconfig, base_url: str = "http://127.0.0.1") -> None:
        # Enable High DPI scaling for 4K screens
        if not QApplication.instance():
             # Set attributes before creating the app
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)

        self._app = QApplication.instance() or QApplication(sys.argv)
        
        """Create QApplication and open a window for every configured display."""

        # Must be created in the main thread before any widgets
        self._app = QApplication.instance() or QApplication(sys.argv)

        monitors = []
        if get_monitors:
            try:
                monitors = get_monitors()
                print(f"[QtWindowManager] Detected {len(monitors)} monitors: {monitors}")
            except Exception as e:
                print(f"[QtWindowManager] Could not enumerate monitors: {e}")

        theme_assets_port = int(iniconfig.config["Network"].get("themeassetsport", "8000"))
        manager_ui_port   = int(iniconfig.config["Network"].get("manageruiport",   "8001"))

        # Poll until the HTTP server is ready - avoids the race condition
        # the original code worked around with time.sleep(0.5)
        probe_url = f"{base_url}:{theme_assets_port}/web/splash.html"
        print(f"[QtWindowManager] Waiting for HTTP server at {probe_url} ...")
        if _wait_for_server(probe_url, timeout=15.0):
            print("[QtWindowManager] HTTP server ready.")
        else:
            print("[QtWindowManager] WARNING: HTTP server did not respond in 15s, continuing anyway.")

        # Order: bg -> dmd -> table (table last so it gets focus, matching original)
        window_configs = [
            ("bg",    "bgscreenid"),
            ("dmd",   "dmdscreenid"),
            ("table", "tablescreenid"),
        ]

        for win_name, config_key in window_configs:
            screen_id_str = iniconfig.config["Displays"].get(config_key, "").strip()
            if not screen_id_str:
                continue

            # --- SANITIZATION START: Prevent 'False' from hanging the splash screen ---
            if screen_id_str in ['False', 'None', 'True']:
                screen_id = 0
            else:
                try:
                    screen_id = int(screen_id_str)
                except ValueError:
                    print(f"[QtWindowManager] Warning: Invalid ID '{screen_id_str}' for {win_name}. Using 0.")
                    screen_id = 0
            # --- SANITIZATION END ---

            if monitors and screen_id >= len(monitors):
                print(
                    f"[QtWindowManager] Warning: {config_key}={screen_id} "
                    f"but only {len(monitors)} monitors found, skipping."
                )
                continue

            mon    = monitors[screen_id] if monitors else None
            x      = mon.x      if mon else 0
            y      = mon.y      if mon else 0
            width  = mon.width  if mon else 1920
            height = mon.height if mon else 1080

            # Exact same URL the original chromium_manager builds
            url = f"{base_url}:{theme_assets_port}/web/splash.html?window={win_name}"

            print(f"[QtWindowManager] Creating '{win_name}' window ({width}x{height} at {x},{y}) -> {url}")

            win = _VPinWindow(
                name=win_name,
                url=url,
                x=x, y=y,
                width=width, height=height,
                manager_ui_port=manager_ui_port,
            )
            self._windows.append(win)

        if not self._windows:
            print("[QtWindowManager] No windows configured - check vpinfe.ini [Displays]")
            self._exit_event.set()
            return

        # Load URLs once the Qt event loop is actually running
        QTimer.singleShot(200, self._load_all)
        
    def terminate_all(self) -> None:
        """Close all windows. Equivalent to ChromiumManager.terminate_all."""
        print("[QtWindowManager] Terminating all windows...")
        for win in list(self._windows):
            try:
                win.close()
            except Exception as e:
                print(f"[QtWindowManager] Error closing '{win.name}': {e}")
        self._windows.clear()
        self._exit_event.set()
        print("[QtWindowManager] All windows closed.")

    def wait_for_exit(self) -> None:
        """Block main thread until app quits."""
        if self._app is None:
            return
            
        # 1. Setup heartbeat to catch Ctrl+C (Terminal interrupt)
        import signal
        self._signal_timer = QTimer()
        self._signal_timer.timeout.connect(lambda: None)
        self._signal_timer.start(500)
        signal.signal(signal.SIGINT, signal.SIG_DFL) 

        # 2. Hook into the Qt Quit event (Cmd+Q)
        # This runs right before the GUI disappears
        self._app.aboutToQuit.connect(self._on_app_quit)

        print("[Qt] Event loop running...")
        self._app.exec()
        
        # 3. Ensure we flag the main loop to finish
        self._exit_event.set()
        print("[Qt] Event loop exited.")

    def _on_app_quit(self):
        """Called when Cmd+Q is pressed."""
        print("[Qt] Quit requested (Cmd+Q). Cleaning up...")
        # Signal the main python script to stop waiting
        self._exit_event.set()
        
        # Optional: Force close all windows just to be safe
        for win in self._windows:
            win.close()

    def get_process(self, window_name: str):
        """Stub - no subprocess in Qt mode. Returns None."""
        return None

    @property
    def is_running(self) -> bool:
        return bool(self._windows) and not self._exit_event.is_set()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        table_window = None
        for win in self._windows:
            win.load_url()
            if win.name == 'table':
                table_window = win
        
        # Force focus to the table window so Gamepads work immediately
        if table_window:
            setup_native_dialogs(table_window) # This connects the bridge
            table_window.raise_()
            table_window.activateWindow()
            table_window.setFocus()
# ---------------------------------------------------------------------------
# Native Dialog Bridge (Async Version)
# ---------------------------------------------------------------------------
class _DialogWorker(QObject):
    request_signal = Signal(str, object) 

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.request_signal.connect(self._show_dialog)

    def _show_dialog(self, mode, callback):
        path = ""
        try:
            if mode == 'folder':
                path = QFileDialog.getExistingDirectory(self.parent_window, "Select Directory")
            else:
                path, _ = QFileDialog.getOpenFileName(self.parent_window, "Select File")
        except Exception as e:
            print(f"[Qt] Dialog Error: {e}")
        
        # Send the result back to the waiting async function
        callback(path)

_global_dialog_bridge = None

def setup_native_dialogs(main_window):
    global _global_dialog_bridge
    _global_dialog_bridge = _DialogWorker(main_window)
    print("[Qt] Native dialog bridge initialized.")

async def pick_native_path(mode='folder'):
    if not _global_dialog_bridge:
        print("[Qt] Error: Bridge not initialized. Did 'table' window load?")
        return None

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    
    def on_done(result):
        # Safely return the result to the NiceGUI thread
        loop.call_soon_threadsafe(future.set_result, result)

    _global_dialog_bridge.request_signal.emit(mode, on_done)
    return await future