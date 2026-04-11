---
name: desktop-gui
description: Build modern Tkinter desktop apps with custom styling and threading
---

# Desktop GUI Skill (Tkinter)

## Modern Styling
```python
style = ttk.Style()
style.theme_use("clam")

BG = "#f8fafc"           # slate-50
CARD_BG = "#ffffff"
PRIMARY = "#4f46e5"      # indigo-600
SUCCESS = "#059669"      # emerald-600
WARNING = "#d97706"      # amber-600
DANGER = "#dc2626"       # red-600
TEXT = "#1e293b"         # slate-800
TEXT_SEC = "#64748b"     # slate-500

style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 9))
style.configure("TNotebook.Tab", padding=[12, 6], font=("Segoe UI", 9, "bold"))
style.configure("TFrame", background=BG)
style.configure("TLabelframe", background=CARD_BG)
style.configure("TLabelframe.Label", background=BG, font=("Segoe UI", 9, "bold"))
style.configure("Treeview", rowheight=28, background="white", fieldbackground="white")
style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"))
```

## CRITICAL: Threading Rules
Tkinter is single-threaded. NEVER block the main loop.

### Pattern: Background Task with GUI Update
```python
def _do_something(self):
    self._label.config(text="Working...", foreground="orange")
    
    def _run():
        try:
            result = heavy_operation()  # Runs in thread
            # Update GUI from thread — MUST use root.after()
            self.root.after(0, lambda: self._label.config(
                text=f"Done: {result}", foreground="green"))
        except Exception as e:
            self.root.after(0, lambda: self._label.config(
                text=f"Error: {e}", foreground="red"))
    
    threading.Thread(target=_run, daemon=True).start()
```

### Pattern: Non-blocking Async DB Call
```python
def _run_async_bg(coro, callback=None):
    """Run async coro in background, call callback(result) on GUI thread."""
    def _worker():
        future = asyncio.run_coroutine_threadsafe(coro, _loop)
        try:
            result = future.result(timeout=30)
        except Exception:
            result = None
        if callback and _root:
            _root.after(0, lambda: callback(result))
    threading.Thread(target=_worker, daemon=True).start()
```

## Layout
- ttk.Notebook for tabs
- ttk.LabelFrame for grouped sections (padding=10)
- ttk.Treeview + Scrollbar for lists
- Pack geometry: fill=tk.BOTH, expand=True
- Consistent padding: 16px outer, 6px between elements

## Window Management
- root.withdraw() to hide (not destroy)
- root.deiconify() to show
- root.lift() + root.focus_force() to bring to front
- root.protocol("WM_DELETE_WINDOW", self._on_close) to hide on X

## Hotkeys
- Use `keyboard` library on Windows (pynput as fallback for macOS)
- Re-register with `keyboard.unhook_all()` then `keyboard.add_hotkey()`
- Store in user_prefs.yaml, load on startup
