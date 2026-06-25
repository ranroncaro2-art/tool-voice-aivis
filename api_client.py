import requests
import wave
import io
import os
import config
import gradio as gr

def fetch_speakers_list(selected_engine=None):
    """Queries GET /speakers from the selected Engine (AivisSpeech or VOICEVOX) and formats the results."""
    if not selected_engine:
        selected_engine = config.ACTIVE_ENGINE
        
    engine_url = config.ENGINES.get(selected_engine, "http://127.0.0.1:10101")
    try:
        response = requests.get(f"{engine_url}/speakers", timeout=2)
        if response.status_code == 200:
            speakers_data = response.json()
            choices = []
            speaker_map = {}
            for sp in speakers_data:
                sp_name = sp.get("name", "Unknown")
                for style in sp.get("styles", []):
                    style_name = style.get("name", "")
                    style_id = style.get("id")
                    display_name = f"[{selected_engine}] {sp_name} ({style_name})"
                    choices.append(display_name)
                    speaker_map[display_name] = style_id
            if choices:
                return choices, speaker_map
    except Exception as e:
        print(f"[Warning] Could not connect to {selected_engine} Engine to get speakers: {e}")
    return [f"Chưa kết nối {selected_engine}"], {}

def update_speakers(selected_engine=None):
    """Updates the cached speaker choices and map in config."""
    if not selected_engine:
        selected_engine = config.ACTIVE_ENGINE
    choices, speaker_map = fetch_speakers_list(selected_engine)
    config.GLOBAL_SPEAKER_CHOICES = choices
    config.GLOBAL_SPEAKER_MAP = speaker_map
    return choices

def handle_refresh(selected_engine=None):
    """Triggers speaker fetch and updates the speaker dropdown choices in the UI."""
    if not selected_engine:
        selected_engine = config.ACTIVE_ENGINE
    choices = update_speakers(selected_engine)
    default_val = choices[0] if choices else None
    return gr.update(choices=choices, value=default_val, interactive=True)

def handle_engine_change(selected_engine):
    """Updates the active engine configuration and returns updated speaker choices."""
    config.ACTIVE_ENGINE = selected_engine
    return handle_refresh(selected_engine)

def get_wav_duration(wav_bytes):
    """Parses binary WAV data to determine its exact duration in seconds."""
    try:
        with wave.open(io.BytesIO(wav_bytes), 'rb') as wav:
            frames = wav.getnframes()
            rate = wav.getframerate()
            return frames / float(rate)
    except Exception as e:
        print(f"Error parsing WAV duration: {e}")
    return 1.0

def choose_output_directory(current_dir):
    """Opens a native Windows folder picker dialog instantly via ctypes, falling back to subprocess methods if needed."""
    import sys
    import os
    import subprocess
    import threading
    import queue
    
    init_dir = current_dir if (current_dir and os.path.isdir(current_dir)) else os.getcwd()
    init_dir_normalized = os.path.abspath(init_dir).replace('/', '\\')
    
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes

            # Set explicit argtypes/restype for SendMessageW to avoid 64-bit address overflow
            ctypes.windll.user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            ctypes.windll.user32.SendMessageW.restype = wintypes.LPARAM

            class BROWSEINFO(ctypes.Structure):
                _fields_ = [
                    ("hwndOwner", wintypes.HWND),
                    ("pidlRoot", ctypes.c_void_p),
                    ("pszDisplayName", wintypes.LPWSTR),
                    ("lpszTitle", wintypes.LPWSTR),
                    ("ulFlags", wintypes.UINT),
                    ("lpfn", ctypes.c_void_p),
                    ("lParam", wintypes.LPARAM),
                    ("iImage", ctypes.c_int)
                ]

            BIF_RETURNONLYFSDIRS = 0x0001
            BIF_NEWDIALOGSTYLE = 0x0040
            BFFM_INITIALIZED = 1
            BFFM_SETSELECTIONW = 0x467

            BrowseCallbackProc = ctypes.WINFUNCTYPE(
                ctypes.c_int,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.LPARAM,
                wintypes.LPARAM
            )

            def browse_callback(hwnd, uMsg, lParam, lpData):
                if uMsg == BFFM_INITIALIZED:
                    ctypes.windll.user32.SendMessageW(hwnd, BFFM_SETSELECTIONW, 1, lpData)
                return 0

            def ask_directory_thread(init_path, res_queue):
                try:
                    shell32 = ctypes.windll.shell32
                    ole32 = ctypes.windll.ole32
                    user32 = ctypes.windll.user32

                    # Explicitly define function signatures for safety
                    shell32.SHBrowseForFolderW.argtypes = [ctypes.c_void_p]
                    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
                    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
                    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
                    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
                    ole32.CoInitialize.restype = ctypes.c_long

                    # 1. Initialize COM as STA on this clean thread
                    ole32.CoInitialize(None)

                    # 2. Get active window handle (browser/application) to parent the dialog topmost
                    hwnd_owner = user32.GetForegroundWindow()

                    cb_func = BrowseCallbackProc(browse_callback)
                    display_name = ctypes.create_unicode_buffer(260)

                    bi = BROWSEINFO()
                    bi.hwndOwner = hwnd_owner
                    bi.pidlRoot = None
                    bi.pszDisplayName = ctypes.cast(display_name, wintypes.LPWSTR)
                    bi.lpszTitle = "Chọn Thư Mục Dự Án / Đầu Ra"
                    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
                    bi.lpfn = ctypes.cast(cb_func, ctypes.c_void_p)
                    
                    path_ptr = ctypes.c_wchar_p(init_path)
                    bi.lParam = ctypes.cast(path_ptr, ctypes.c_void_p).value

                    # 3. Open Dialog
                    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
                    
                    selected = None
                    if pidl:
                        path_buf = ctypes.create_unicode_buffer(260)
                        if shell32.SHGetPathFromIDListW(pidl, path_buf):
                            selected = path_buf.value
                        ole32.CoTaskMemFree(pidl)
                    
                    ole32.CoUninitialize()
                    res_queue.put((True, selected))
                except Exception as thread_ex:
                    res_queue.put((False, thread_ex))

            # Run dialog on dedicated thread to ensure COM STA is clean and responsive
            res_queue = queue.Queue()
            t = threading.Thread(target=ask_directory_thread, args=(init_dir_normalized, res_queue), daemon=True)
            t.start()
            
            success, result = res_queue.get()
            if success:
                if result:
                    return os.path.abspath(result)
                else:
                    return current_dir  # Closed/cancelled
            else:
                raise result  # Propagate thread exception to trigger fallback
        except Exception as e:
            print(f"Error in ctypes folder picker: {e}")

    # Fallback to powershell (only on Windows, if ctypes failed)
    if os.name == 'nt':
        ps_script = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$dialog.SelectedPath = '{init_dir_normalized.replace(chr(92), chr(47))}'; "
            "$dialog.Description = 'Chọn Thư Mục'; "
            "if ($dialog.ShowDialog() -eq 'OK') { Write-Output $dialog.SelectedPath }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=120
            )
            selected = result.stdout.strip()
            if selected:
                return os.path.abspath(selected)
        except Exception as e:
            print(f"Error in powershell folder picker fallback: {e}")
            
    # Fallback to tkinter script (mostly for non-Windows, or if everything else fails)
    script = (
        "import sys, os, tkinter as tk; "
        "from tkinter import filedialog; "
        "root = tk.Tk(); "
        "root.withdraw(); "
        "root.attributes('-topmost', True); "
        "init_dir = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.getcwd(); "
        "path = filedialog.askdirectory(initialdir=init_dir, title='Chọn Thư Mục'); "
        "print(path if path else '')"
    )
    
    try:
        python_exe = sys.executable if not getattr(sys, 'frozen', False) else "python"
        result = subprocess.run(
            [python_exe, "-c", script, current_dir or ""],
            capture_output=True,
            text=True,
            timeout=120
        )
        selected = result.stdout.strip()
        if selected:
            return os.path.abspath(selected)
    except Exception as e:
        print(f"Error in folder picker subprocess fallback: {e}")
        
    return current_dir
