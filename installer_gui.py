# -*- coding: utf-8 -*-
"""
KIT Installer — offline USB install kit with Linux-repo-style GUI.
Tab 1: install from USB (groups sidebar + program cards with icons).
Tab 2: download from WinGet.
English base + Greek. Auto-detects Windows language.
"""
import json, re, subprocess, sys, threading, queue, ctypes, os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk, ImageDraw

# ── Icon extraction via ctypes only (no pywin32 needed) ──────
import ctypes.wintypes as wint
from ctypes import c_void_p, c_uint, c_int, POINTER, Structure, byref, sizeof, memmove, create_string_buffer


class BITMAP(Structure):
    _fields_ = [("bmType", c_uint), ("bmWidth", c_uint), ("bmHeight", c_uint),
                ("bmWidthBytes", c_uint), ("bmPlanes", wint.WORD),
                ("bmBitsPixel", wint.WORD), ("bmBits", c_void_p)]


class ICONINFO(Structure):
    _fields_ = [("fIcon", wint.BOOL), ("xHotspot", wint.DWORD),
                ("yHotspot", wint.DWORD), ("hbmMask", c_void_p),
                ("hbmColor", c_void_p)]


class RGBQUAD(Structure):
    _fields_ = [("rgbBlue", wint.BYTE), ("rgbGreen", wint.BYTE),
                ("rgbRed", wint.BYTE), ("rgbReserved", wint.BYTE)]


class BITMAPINFOHEADER(Structure):
    _fields_ = [("biSize", wint.DWORD), ("biWidth", wint.LONG),
                ("biHeight", wint.LONG), ("biPlanes", wint.WORD),
                ("biBitCount", wint.WORD), ("biCompression", wint.DWORD),
                ("biSizeImage", wint.DWORD), ("biXPelsPerMeter", wint.LONG),
                ("biYPelsPerMeter", wint.LONG), ("biClrUsed", wint.DWORD),
                ("biClrImportant", wint.DWORD)]


class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


_gdi32 = ctypes.windll.gdi32
_user32 = ctypes.windll.user32
_shell32 = ctypes.windll.shell32

_gdi32.GetObjectW.argtypes = [c_void_p, c_int, c_void_p]
_gdi32.GetObjectW.restype = c_int
_gdi32.CreateCompatibleDC.argtypes = [c_void_p]
_gdi32.CreateCompatibleDC.restype = c_void_p
_gdi32.CreateCompatibleBitmap.argtypes = [c_void_p, c_int, c_int]
_gdi32.CreateCompatibleBitmap.restype = c_void_p
_gdi32.SelectObject.argtypes = [c_void_p, c_void_p]
_gdi32.SelectObject.restype = c_void_p
_gdi32.DeleteDC.argtypes = [c_void_p]
_gdi32.DeleteDC.restype = c_int
_gdi32.DeleteObject.argtypes = [c_void_p]
_gdi32.DeleteObject.restype = c_int
_gdi32.GetDIBits.argtypes = [c_void_p, c_void_p, c_uint, c_uint, c_void_p,
                              POINTER(BITMAPINFO), c_uint]
_gdi32.GetDIBits.restype = c_int
_user32.GetDC.argtypes = [c_void_p]
_user32.GetDC.restype = c_void_p
_user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
_user32.ReleaseDC.restype = c_int
_user32.GetIconInfo.argtypes = [c_void_p, POINTER(ICONINFO)]
_user32.GetIconInfo.restype = wint.BOOL
_user32.DrawIconEx.argtypes = [c_void_p, c_int, c_int, c_void_p, c_int,
                                c_int, c_uint, c_void_p, c_uint]
_user32.DrawIconEx.restype = wint.BOOL
_user32.DestroyIcon.argtypes = [c_void_p]
_user32.DestroyIcon.restype = wint.BOOL
_shell32.ExtractIconW.argtypes = [c_void_p, wint.LPCWSTR, c_uint]
_shell32.ExtractIconW.restype = c_void_p


def extract_icon_pil(filepath, size=48):
    """Extract first icon from .exe/.dll as a PIL RGBA Image, size×size."""
    ext = Path(filepath).suffix.lower()
    if ext not in (".exe", ".dll", ".ico"):
        return None
    try:
        hicon = _shell32.ExtractIconW(None, str(filepath), 0)
        if not hicon:
            return None
        hdc = _user32.GetDC(None)
        memdc = _gdi32.CreateCompatibleDC(hdc)
        hbmp = _gdi32.CreateCompatibleBitmap(hdc, size, size)
        old_bmp = _gdi32.SelectObject(memdc, hbmp)
        _user32.DrawIconEx(memdc, 0, 0, hicon, size, size, 0, None, 3)
        # read bitmap bits via GetDIBits
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = size
        bmi.bmiHeader.biHeight = -size  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        row_bytes = size * 4
        buf = create_string_buffer(row_bytes * size)
        _gdi32.GetDIBits(memdc, hbmp, 0, size, buf, byref(bmi), 0)
        # cleanup
        _gdi32.SelectObject(memdc, old_bmp)
        _gdi32.DeleteObject(hbmp)
        _gdi32.DeleteDC(memdc)
        _user32.ReleaseDC(None, hdc)
        _user32.DestroyIcon(hicon)
        img = Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1)
        return img
    except Exception:
        return None


def make_default_icon(size=48):
    """Create a grey placeholder icon."""
    img = Image.new("RGBA", (size, size), (200, 200, 200, 255))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(160, 160, 180, 255))
    draw.text((size // 2 - 5, size // 2 - 7), "?", fill=(80, 80, 100, 255))
    return img


# ── translations ───────────────────────────────────────────────
TR = {
    "en": {
        "app_title": "KIT Installer — offline install from USB",
        "heading": "KIT Installer",
        "kit_path": "Kit folder: {path}",
        "tab_install": "  1 · Install from USB  ",
        "tab_download": "  2 · Download from WinGet  ",
        "all_group": "📁 All",
        "group_root": "📁 (root)",
        "group_label": "📁 {g}",
        "search_ph": "Search programs…",
        "btn_search_w": "🔍",
        "sel_all": "✓ All", "sel_none": "✗ None",
        "refresh": "↻ Refresh", "new_group": "+ New group",
        "btn_install": "INSTALL SELECTED",
        "no_selection": "No program selected.",
        "confirm_install": "Install {n} programs in order?\n\n{list}",
        "start_install": "Starting installation of {n} programs…",
        "grp_new_done": '✔ Group "{name}" created → {path}',
        "grp_bad_chars": "The name contains forbidden characters.",
        "grp_error": "Could not create it:\n{e}",
        "grp_prompt": "Group name (becomes a folder under installs\\):",
        "dir_empty": "The installs\\ folder is empty or missing.\nPut installers there.",
        "run_silent": "  → running silently: {args}",
        "run_msi": "  → msiexec silent install…",
        "skip_unknown": "  ⚠ No silent switch — skipped (add to apps.json).",
        "ok": "  ✔ OK", "fail": "  ✘ Failed (code {rc})", "err": "  ✘ Error: {e}",
        "sep": "=" * 55,
        "done_summary": "DONE — ok: {ok} · fail: {fail} · skip: {skip}",
        "search_hint": "Try: 7zip · chrome · vlc · libreoffice · sumatrapdf · anydesk",
        "search_label": "Search:", "btn_search_msg": "Search in WinGet",
        "dl_to_label": "Into folder:", "btn_download": "⬇ Download selected",
        "dl_pick_first": "Select programs from the list first.",
        "dl_start": "Downloading {n} packages into: {path}",
        "dl_ok": "  ✔ Downloaded: {got}",
        "dl_ok_done": "  ✔ Done",
        "dl_fail": "  ✘ Download failed:\n{tail}",
        "dl_summary": "DOWNLOADS — ok: {ok} · fail: {fail}",
        "dl_after": 'Tab 1 → "Refresh" to see the new files.',
        "col_pname": "Program", "col_pid": "ID (WinGet)", "col_pver": "Version",
        "status": " Status ",
        "searching": "🔍 Searching WinGet for: {q}",
        "found_n": "  ✔ {n} results",
        "not_found": "  ⚠ nothing found",
        "log_sep": "=" * 55,
        "lang_label": "Language:", "lang_en": "English", "lang_el": "Ελληνικά",
        "card_info": "📄 {name}\n📏 {size}\n🪟 Silent: {silent}",
        "n_programs": "{n} programs",
        "install_tooltip": "Select programs above, then click install",
    },
    "el": {
        "app_title": "KIT Installer — εγκατάσταση από USB (offline)",
        "heading": "KIT Installer",
        "kit_path": "Φάκελος κιτ: {path}",
        "tab_install": "  1 · Εγκατάσταση από USB  ",
        "tab_download": "  2 · Λήψη από WinGet  ",
        "all_group": "📁 Όλα",
        "group_root": "📁 (ρίζα)",
        "group_label": "📁 {g}",
        "search_ph": "Αναζήτηση…",
        "btn_search_w": "🔍",
        "sel_all": "✓ Όλα", "sel_none": "✗ Κανένα",
        "refresh": "↻ Ανανέωση", "new_group": "+ Νέα ομάδα",
        "btn_install": "ΕΓΚΑΤΑΣΤΑΣΗ ΕΠΙΛΕΓΜΕΝΩΝ",
        "no_selection": "Δεν επέλεξες κανένα πρόγραμμα.",
        "confirm_install": "Να εγκατασταθούν {n} προγράμματα με τη σειρά;\n\n{list}",
        "start_install": "Ξεκινάει εγκατάσταση {n} προγραμμάτων…",
        "grp_new_done": '✔ Δημιουργήθηκε η ομάδα «{name}» → {path}',
        "grp_bad_chars": "Το όνομα περιέχει μη επιτρεπόμενους χαρακτήρες.",
        "grp_error": "Δεν μπόρεσα να τη φτιάξω:\n{e}",
        "grp_prompt": "Όνομα ομάδας (θα γίνει φάκελος στο installs\\):",
        "dir_empty": "Ο φάκελος installs\\ είναι άδειος ή λείπει.\nΒάλε installers εκεί.",
        "run_silent": "  → τρέχω σιωπηλά: {args}",
        "run_msi": "  → msiexec σιωπηλή εγκατάσταση…",
        "skip_unknown": "  ⚠ ΔΕΝ ΞΕΡΩ silent switch — παραλείφθηκε (πρόσθεσέ το στο apps.json).",
        "ok": "  ✔ Επιτυχία", "fail": "  ✘ Αποτυχία (κωδικός {rc})",
        "err": "  ✘ Σφάλμα: {e}",
        "sep": "=" * 55,
        "done_summary": "ΤΕΛΟΣ — επιτυχία: {ok} · αποτυχία: {fail} · παραλείφθηκαν: {skip}",
        "search_hint": "Δοκίμασε: 7zip · chrome · vlc · libreoffice · sumatrapdf · anydesk",
        "search_label": "Αναζήτηση:", "btn_search_msg": "Αναζήτηση στο WinGet",
        "dl_to_label": "Στον φάκελο:", "btn_download": "⬇ Κατέβασμα επιλεγμένων",
        "dl_pick_first": "Επίλεξε πρώτα προγράμματα από τη λίστα.",
        "dl_start": "Κατέβασμα {n} πακέτων στο: {path}",
        "dl_ok": "  ✔ Κατέβηκε: {got}",
        "dl_ok_done": "  ✔ Ολοκληρώθηκε",
        "dl_fail": "  ✘ Αποτυχία λήψης:\n{tail}",
        "dl_summary": "ΛΗΨΕΙΣ — επιτυχία: {ok} · αποτυχία: {fail}",
        "dl_after": 'Καρτέλα 1 → "Ανανέωση" για να δεις τα νέα αρχεία.',
        "col_pname": "Πρόγραμμα", "col_pid": "ID (WinGet)", "col_pver": "Έκδοση",
        "status": " Κατάσταση ",
        "searching": "🔍 Αναζήτηση στο WinGet: {q}",
        "found_n": "  ✔ {n} αποτελέσματα",
        "not_found": "  ⚠ δεν βρέθηκε τίποτα",
        "log_sep": "=" * 55,
        "lang_label": "Γλώσσα:", "lang_en": "English", "lang_el": "Ελληνικά",
        "card_info": "📄 {name}\n📏 {size}\n🪟 Σιωπηλά: {silent}",
        "n_programs": "{n} προγράμματα",
        "install_tooltip": "Επίλεξε προγράμματα πάνω, μετά πάτα εγκατάσταση",
    },
}

# ── config / paths ────────────────────────────────────────────
CONFIG_FILE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent / "config.json"


def detect_lang():
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "el" if lid == 0x408 else "en"
    except Exception:
        return "en"


def load_lang():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("lang", "en")
    except Exception:
        pass
    return detect_lang()


def save_lang(lang):
    try:
        CONFIG_FILE.write_text(json.dumps({"lang": lang}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


BASE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
INSTALL_DIR = BASE / "installs"
RULES_FILE = BASE / "apps.json"

BUILTIN_RULES = {
    "7zip": ["/S"], "7-zip": ["/S"], "chrome": ["--silent-install"], "vlc": ["/S"],
    "libreoffice": ["/S"], "sumatra": ["/S"], "anydesk": ["/S"],
}
MSI_ARGS = ["/qn", "/norestart"]
APP_NAMES = {
    "7zip": "7-Zip", "7-zip": "7-Zip", "chrome": "Google Chrome",
    "vlc": "VLC media player", "libreoffice": "LibreOffice",
    "sumatra": "SumatraPDF", "anydesk": "AnyDesk",
    "pdfgear": "PDFgear", "onlyoffice": "ONLYOFFICE",
}


def load_user_rules():
    rules = {}
    try:
        if RULES_FILE.exists():
            data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            rules = {k.lower(): v for k, v in data.get("rules", {}).items()}
    except Exception as e:
        print("apps.json:", e)
    return rules


USER_RULES = load_user_rules()


def display_name(filename: str) -> str:
    low = filename.lower()
    for k, v in APP_NAMES.items():
        if k in low:
            return v
    return Path(filename).stem


def rule_for(filename: str):
    low = filename.lower()
    for key, args in {**BUILTIN_RULES, **USER_RULES}.items():
        if key in low:
            return list(args), True
    return None, False


def group_dirs():
    if not INSTALL_DIR.exists():
        return []
    return sorted(p.name for p in INSTALL_DIR.iterdir() if p.is_dir())


def scan():
    out = []
    if not INSTALL_DIR.exists():
        return out
    for grp in sorted(p for p in INSTALL_DIR.iterdir() if p.is_dir()):
        for f in sorted(grp.iterdir()):
            if f.suffix.lower() in (".exe", ".msi"):
                out.append((grp.name, f, display_name(f.name), f.stat().st_size))
    for f in sorted(INSTALL_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in (".exe", ".msi"):
            out.append(("", f, display_name(f.name), f.stat().st_size))
    return out


def fmt_size(n):
    return f"{n / 1_000_000:.1f} MB" if n > 1_000_000 else f"{n // 1024} KB"


def decode_best(raw: bytes) -> str:
    for enc in ("utf-8", "cp1253", "cp437", "cp850"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def winget_search(query):
    cmd = ["winget", "search", "--query", query, "--source", "winget",
           "--accept-source-agreements", "--disable-interactivity"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=90)
    except Exception as e:
        return [], str(e)
    text = decode_best((r.stdout or b"") + b"\n" + (r.stderr or b""))
    rows = []
    for line in text.splitlines():
        if line.strip().startswith("---"):
            continue
        if re.search(r"^\s*Name\s+Id\s+Version", line):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 3:
            name, ident, version = parts[0], parts[1], parts[2].split()[0]
            if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.[A-Za-z0-9._-]+$", ident):
                rows.append((name, ident, version))
    return rows, "" if (rows or r.returncode == 0) else ("no results")


# ── icon cache ────────────────────────────────────────────────
_ICON_CACHE: dict[str, ImageTk.PhotoImage] = {}
_ICON_PIL_CACHE: dict[str, Image.Image] = {}


def get_icon_photo(filepath, size=48):
    """Return an ImageTk.PhotoImage for the given .exe file."""
    if filepath in _ICON_CACHE:
        return _ICON_CACHE[filepath]
    if filepath not in _ICON_PIL_CACHE:
        pil = extract_icon_pil(filepath, size) or make_default_icon(size)
        _ICON_PIL_CACHE[filepath] = pil
    photo = ImageTk.PhotoImage(_ICON_PIL_CACHE[filepath])
    _ICON_CACHE[filepath] = photo
    return photo


# ── Tooltip ───────────────────────────────────────────────────
class ToolTip:
    """A transparent tooltip that follows the mouse, showing program info."""

    def __init__(self, master, text_fn, delay=400):
        self.master = master
        self.text_fn = text_fn
        self.delay = delay
        self._id = None
        self._tw = None

    def schedule(self, event):
        self.cancel()
        self._id = self.master.after(self.delay, lambda: self._show(event))

    def cancel(self):
        if self._id:
            self.master.after_cancel(self._id)
            self._id = None
        self._hide()

    def _show(self, event):
        txt = self.text_fn()
        if not txt:
            return
        x = self.master.winfo_pointerx() + 14
        y = self.master.winfo_pointery() + 8
        self._tw = tk.Toplevel(self.master)
        self._tw.wm_overrideredirect(True)
        self._tw.wm_geometry(f"+{x}+{y}")
        self._tw.attributes("-topmost", True)
        lbl = tk.Label(self._tw, text=txt, justify="left",
                       bg="#fffeec", fg="#221733", relief="solid",
                       borderwidth=1, font=("Segoe UI", 9), padx=8, pady=4)
        lbl.pack()

    def _hide(self):
        if self._tw:
            self._tw.destroy()
            self._tw = None


# ── Program Card ──────────────────────────────────────────────
CARD_W, CARD_H = 180, 152
PAD = 8


class ProgramCard(tk.Frame):
    """A card widget showing icon, name, size, and selection checkbox."""

    def __init__(self, parent, grp_name, filepath, dname, size_bytes,
                 silent_known, on_toggle, **kw):
        super().__init__(parent, bg="#fcfaf6", highlightbackground="#ddd",
                         highlightthickness=1, **kw)
        self.filepath = filepath
        self.grp_name = grp_name
        self.dname = dname
        self.size_bytes = size_bytes
        self.silent_known = silent_known
        self._checked = tk.BooleanVar(value=False)
        self.on_toggle = on_toggle

        self.configure(width=CARD_W, height=CARD_H)
        self.pack_propagate(False)
        self.grid_propagate(False)

        # icon
        try:
            photo = get_icon_photo(str(filepath), 48)
            self.icon_lbl = tk.Label(self, image=photo, bg="#fcfaf6")
            self.icon_lbl.image = photo  # keep ref
        except Exception:
            self.icon_lbl = tk.Label(self, text="□", bg="#fcfaf6", font=("Segoe UI", 24))
        self.icon_lbl.pack(pady=(6, 2))

        # name
        self.name_lbl = tk.Label(self, text=dname, bg="#fcfaf6",
                                 font=("Segoe UI", 9, "bold"), fg="#221733",
                                 wraplength=CARD_W - 16)
        self.name_lbl.pack()

        # size + silent badge
        extra = fmt_size(size_bytes)
        if not silent_known:
            extra += " ⚠"
        self.info_lbl = tk.Label(self, text=extra, bg="#fcfaf6",
                                 font=("Consolas", 8), fg="#888")
        self.info_lbl.pack()

        # checkbox
        self.cb = tk.Checkbutton(self, variable=self._checked,
                                 bg="#fcfaf6", activebackground="#fcfaf6",
                                 command=self._fire_toggle,
                                 font=("Segoe UI", 8))
        self.cb.pack(pady=(2, 4))

        # hover effect
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

        # tooltip
        self.tip = ToolTip(self, self._tip_text, delay=500)

    def _tip_text(self):
        silent = self.silent_known
        return f"📄 {self.dname}\n📏 {fmt_size(self.size_bytes)}\n🪟 Silent: {'✓' if silent else '✗'}"

    def _on_enter(self, e):
        self.configure(bg="#f4efe6")
        for c in self.winfo_children():
            try:
                c.configure(bg="#f4efe6")
            except Exception:
                pass
        self.tip.schedule(e)

    def _on_leave(self, e):
        self.configure(bg="#fcfaf6")
        for c in self.winfo_children():
            try:
                c.configure(bg="#fcfaf6")
            except Exception:
                pass
        self.tip.cancel()

    @property
    def checked(self):
        return self._checked.get()

    @checked.setter
    def checked(self, val):
        self._checked.set(val)

    def _fire_toggle(self):
        if self.on_toggle:
            self.on_toggle()


# ── main app ──────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.lang = load_lang()
        self.t = TR[self.lang]
        self.title(self.t["app_title"])
        self.geometry("920x760")
        self.minsize(780, 600)
        self.configure(bg="#f4f1ea")
        self._all_items: list = []
        self._filtered_items: list = []
        self._cards: list[ProgramCard] = []
        self._current_group = "all"
        self._search_text = ""
        self.q = queue.Queue()
        self.q2 = queue.Queue()
        self._build()
        self.after(120, self._drain)
        self.after(150, self._drain2)
        self.refresh()

    # ── build / rebuild ──
    def _build(self):
        # top bar
        head = tk.Frame(self, bg="#f4f1ea")
        head.pack(fill="x", padx=14, pady=(10, 0))
        left = tk.Frame(head, bg="#f4f1ea")
        left.pack(side="left")
        tk.Label(left, text=self.t["heading"], font=("Segoe UI", 19, "bold"),
                 bg="#f4f1ea", fg="#221733").pack(anchor="w")
        tk.Label(left, text=self.t["kit_path"].format(path=BASE),
                 font=("Segoe UI", 9), bg="#f4f1ea", fg="#666").pack(anchor="w")
        langbox = tk.Frame(head, bg="#f4f1ea")
        langbox.pack(side="right")
        tk.Label(langbox, text=self.t["lang_label"], bg="#f4f1ea",
                 font=("Segoe UI", 9), fg="#666").pack(side="left", padx=4)
        self.langvar = tk.StringVar(value=self.lang)
        for code in ("en", "el"):
            ttk.Radiobutton(langbox, text=TR[code]["lang_" + code], value=code,
                            variable=self.langvar,
                            command=lambda: self._switch_lang()).pack(side="left")

        # notebook
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=6)
        self.tab_install = ttk.Frame(nb)
        self.tab_wget = ttk.Frame(nb)
        nb.add(self.tab_install, text=self.t["tab_install"])
        nb.add(self.tab_wget, text=self.t["tab_download"])
        self._build_tab1()
        self._build_tab2()
        self._build_log()

    def _switch_lang(self):
        code = self.langvar.get()
        if code == self.lang:
            return
        self.lang = code
        self.t = TR[code]
        save_lang(code)
        for w in self.winfo_children():
            w.destroy()
        self.q = queue.Queue()
        self.q2 = queue.Queue()
        self._build()
        self.refresh()
        self.log(self.t["heading"] + " — " + TR[code]["lang_" + code])

    def _build_log(self):
        lf = tk.LabelFrame(self, text=self.t["status"], font=("Segoe UI", 9),
                           bg="#f4f1ea", fg="#221733")
        lf.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._logtxt = tk.Text(lf, height=7, font=("Consolas", 9), bg="#fffdf8",
                               relief="flat", wrap="word")
        self._logtxt.pack(fill="both", expand=True, padx=6, pady=6)
        self._logtxt.config(state="disabled")

    def log(self, msg):
        self._logtxt.config(state="normal")
        self._logtxt.insert("end", msg + "\n")
        self._logtxt.see("end")
        self._logtxt.config(state="disabled")

    def _drain(self):
        try:
            while True:
                self.log(self.q.get_nowait())
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _drain2(self):
        try:
            while True:
                kind, payload = self.q2.get_nowait()
                if kind == "result":
                    self.tree2.insert("", "end", values=payload)
                elif kind == "done":
                    self.btn_search2.config(state="normal")
                    self.btn_dl.config(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._drain2)

    # ════════════ TAB 1 ════════════
    def _build_tab1(self):
        main_frame = tk.Frame(self.tab_install, bg="#f4f1ea")
        main_frame.pack(fill="both", expand=True)

        # ── search bar ──
        search_row = tk.Frame(main_frame, bg="#f4f1ea")
        search_row.pack(fill="x", pady=(6, 4), padx=4)
        self.ent_search = ttk.Entry(search_row, font=("Segoe UI", 11), width=40)
        self.ent_search.pack(side="left", padx=(0, 4), ipady=2)
        self.ent_search.insert(0, "")
        self.ent_search.bind("<KeyRelease>", lambda e: self._on_search())
        # placeholder effect
        self._search_ph = True

        # ── sidebar + cards ──
        body = tk.Frame(main_frame, bg="#f4f1ea")
        body.pack(fill="both", expand=True)

        # -- sidebar --
        side = tk.Frame(body, bg="#ede9e0", width=160)
        side.pack(side="left", fill="y", padx=(0, 6))
        side.pack_propagate(False)

        tk.Label(side, text="Groups", bg="#ede9e0", fg="#221733",
                 font=("Segoe UI", 10, "bold")).pack(pady=(8, 4))
        self.grp_listbox = tk.Listbox(side, bg="#fffdf8", fg="#221733",
                                       selectbackground="#7000f4",
                                       selectforeground="white",
                                       relief="flat", borderwidth=0,
                                       font=("Segoe UI", 9),
                                       activestyle="none")
        self.grp_listbox.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.grp_listbox.bind("<<ListboxSelect>>", lambda e: self._on_group_sel())

        btn_frame = tk.Frame(side, bg="#ede9e0")
        btn_frame.pack(fill="x", padx=4, pady=4)
        ttk.Button(btn_frame, text=self.t["sel_all"], command=self._select_all_card).pack(fill="x", pady=1)
        ttk.Button(btn_frame, text=self.t["sel_none"], command=self._select_none_card).pack(fill="x", pady=1)
        ttk.Button(btn_frame, text=self.t["new_group"], command=self._new_group).pack(fill="x", pady=1)
        ttk.Button(btn_frame, text=self.t["refresh"], command=self.refresh).pack(fill="x", pady=1)

        # -- card grid --
        card_outer = tk.Frame(body, bg="#f4f1ea")
        card_outer.pack(side="left", fill="both", expand=True)
        self.card_canvas = tk.Canvas(card_outer, bg="#f4f1ea", highlightthickness=0)
        self.card_vsb = ttk.Scrollbar(card_outer, orient="vertical", command=self.card_canvas.yview)
        self.card_canvas.configure(yscrollcommand=self.card_vsb.set)
        self.card_vsb.pack(side="right", fill="y")
        self.card_canvas.pack(side="left", fill="both", expand=True)
        self.card_inner = tk.Frame(self.card_canvas, bg="#f4f1ea")
        self.card_canvas_window = self.card_canvas.create_window(0, 0, window=self.card_inner, anchor="nw")
        self.card_inner.bind("<Configure>", self._on_card_inner_config)
        self.card_canvas.bind("<Configure>", self._on_canvas_config)

        # install button
        btn = tk.Button(main_frame, text=self.t["btn_install"],
                        font=("Segoe UI", 13, "bold"), bg="#7000f4", fg="white",
                        activebackground="#5a00c6", activeforeground="white",
                        relief="flat", cursor="hand2", command=self._install_selected)
        btn.pack(fill="x", pady=6, ipady=6, padx=4)

    def _on_card_inner_config(self, event):
        self.card_canvas.configure(scrollregion=self.card_canvas.bbox("all"))

    def _on_canvas_config(self, event):
        self.card_canvas.itemconfig(self.card_canvas_window, width=event.width)

    def _on_search(self):
        self._search_text = self.ent_search.get().strip().lower()
        self._rebuild_cards()

    def _on_group_sel(self):
        sel = self.grp_listbox.curselection()
        if not sel:
            return
        raw = self.grp_listbox.get(sel[0])
        if raw.startswith("📁 "):
            g = raw[2:].strip()
        else:
            g = raw.strip()
        self._current_group = g
        self._rebuild_cards()

    def _rebuild_cards(self):
        for c in self._cards:
            c.destroy()
        self._cards.clear()
        self._filtered_items = []

        for grp, path, dname, size in self._all_items:
            # group filter
            if self._current_group != "all":
                gname = grp if grp else ""
                if gname != self._current_group:
                    continue
            # search filter
            if self._search_text and self._search_text not in dname.lower() and self._search_text not in path.name.lower():
                # also search in filename
                if self._search_text not in path.stem.lower():
                    continue
            self._filtered_items.append((grp, path, dname, size))

        cols = max(1, (self.card_canvas.winfo_width() or 800) // (CARD_W + PAD))
        for idx, (grp, path, dname, size) in enumerate(self._filtered_items):
            silent, known = rule_for(path.name)
            card = ProgramCard(self.card_inner, grp, path, dname, size,
                               known, self._update_install_btn)
            row, col = divmod(idx, cols)
            card.grid(row=row, column=col, padx=PAD // 2, pady=PAD // 2, sticky="nw")
            self._cards.append(card)
        self._update_install_btn()

    def refresh(self):
        self._all_items = scan()
        # rebuild group list
        self.grp_listbox.delete(0, "end")
        self.grp_listbox.insert("end", self.t["all_group"])
        for g in group_dirs():
            self.grp_listbox.insert("end", self.t["group_label"].format(g=g))
        if self._all_items:
            self.grp_listbox.selection_set(0)
            self._current_group = "all"
        else:
            self.log(self.t["dir_empty"])
            self.log(str(INSTALL_DIR))
        self._rebuild_cards()

    def _select_all_card(self):
        for c in self._cards:
            if not c.checked:
                c.checked = True
                c._fire_toggle()

    def _select_none_card(self):
        for c in self._cards:
            if c.checked:
                c.checked = False
                c._fire_toggle()

    def _update_install_btn(self):
        pass  # visual update not needed

    def _new_group(self):
        name = simpledialog.askstring(self.t["new_group"], self.t["grp_prompt"], parent=self)
        if not name:
            return
        name = name.strip().strip("/\\")
        if not name or name in (".", ".."):
            return
        if any(c in name for c in '<>:"|?*'):
            messagebox.showerror(self.t["new_group"], self.t["grp_bad_chars"])
            return
        target = INSTALL_DIR / name
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror(self.t["new_group"], self.t["grp_error"].format(e=e))
            return
        self.log(self.t["grp_new_done"].format(name=name, path=target))
        self.refresh()
        self.refresh_dest()

    def _install_selected(self):
        paths = [c.filepath for c in self._cards if c.checked]
        if not paths:
            messagebox.showinfo(self.t["heading"], self.t["no_selection"])
            return
        listing = "\n".join("• " + p.name for p in paths)
        if not messagebox.askyesno(self.t["heading"],
                                   self.t["confirm_install"].format(n=len(paths), list=listing)):
            return
        self.log(self.t["sep"])
        self.log(self.t["start_install"].format(n=len(paths)))
        threading.Thread(target=self._worker, args=(paths,), daemon=True).start()

    def _worker(self, paths):
        ok = fail = skipped = 0
        for p in paths:
            self.q.put(f"\n▶ {p.name}")
            ext = p.suffix.lower()
            silent, known = rule_for(p.name)
            try:
                if ext == ".msi":
                    cmd = ["msiexec", "/i", str(p), *MSI_ARGS]
                    self.q.put(self.t["run_msi"])
                elif known:
                    cmd = [str(p), *silent]
                    self.q.put(self.t["run_silent"].format(args=" ".join(silent)))
                else:
                    self.q.put(self.t["skip_unknown"])
                    skipped += 1
                    continue
                rc = subprocess.call(cmd)
                if rc == 0:
                    ok += 1
                    self.q.put(self.t["ok"])
                else:
                    fail += 1
                    self.q.put(self.t["fail"].format(rc=rc))
            except Exception as e:
                fail += 1
                self.q.put(self.t["err"].format(e=e))
        self.q.put(self.t["sep"])
        self.q.put(self.t["done_summary"].format(ok=ok, fail=fail, skip=skipped))

    # ════════════ TAB 2 ════════════
    def _build_tab2(self):
        row = tk.Frame(self.tab_wget, bg="#f4f1ea")
        row.pack(fill="x", pady=8)
        tk.Label(row, text=self.t["search_label"], bg="#f4f1ea",
                 font=("Segoe UI", 10)).pack(side="left")
        self.ent_query = ttk.Entry(row, width=28, font=("Segoe UI", 10))
        self.ent_query.pack(side="left", padx=6)
        self.ent_query.bind("<Return>", lambda e: self._do_search())
        self.btn_search2 = ttk.Button(row, text=self.t["btn_search_msg"], command=self._do_search)
        self.btn_search2.pack(side="left", padx=2)

        dest = tk.Frame(self.tab_wget, bg="#f4f1ea")
        dest.pack(fill="x", pady=(0, 6))
        tk.Label(dest, text=self.t["dl_to_label"], bg="#f4f1ea",
                 font=("Segoe UI", 10)).pack(side="left")
        self.dest_var = tk.StringVar()
        self.cmb_dest = ttk.Combobox(dest, textvariable=self.dest_var, width=22, state="readonly")
        self.cmb_dest.pack(side="left", padx=6)
        self.btn_dl = ttk.Button(dest, text=self.t["btn_download"], command=self._do_download)
        self.btn_dl.pack(side="left", padx=8)

        wrap = tk.Frame(self.tab_wget, bg="#f4f1ea")
        wrap.pack(fill="both", expand=True)
        self.tree2 = ttk.Treeview(wrap, columns=("name", "id", "ver"), show="headings",
                                  selectmode="extended")
        for c, key, w in (("name", "col_pname", 300), ("id", "col_pid", 280),
                          ("ver", "col_pver", 100)):
            self.tree2.heading(c, text=self.t[key])
            self.tree2.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.tree2.yview)
        self.tree2.configure(yscrollcommand=vs.set)
        self.tree2.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        tk.Label(self.tab_wget, text=self.t["search_hint"], bg="#f4f1ea", fg="#888",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 6))

    def refresh_dest(self):
        groups = group_dirs() or ["Basic"]
        vals = ["— root of installs —"] + groups
        self.cmb_dest["values"] = vals
        self.cmb_dest.set(vals[1] if len(vals) > 1 else vals[0])

    def _do_search(self):
        q = self.ent_query.get().strip()
        if not q:
            return
        self.tree2.delete(*self.tree2.get_children())
        self.btn_search2.config(state="disabled")
        self.btn_dl.config(state="disabled")
        self.log(self.t["searching"].format(q=q))
        threading.Thread(target=self._search_worker, args=(q,), daemon=True).start()

    def _search_worker(self, q):
        rows, err = winget_search(q)
        if not rows:
            self.q2.put(("done", None))
            self.q.put(self.t["not_found"])
            return
        self.q.put(self.t["found_n"].format(n=len(rows)))
        for r in rows:
            self.q2.put(("result", r))
        self.q2.put(("done", None))

    def _do_download(self):
        sel = [self.tree2.item(i, "values") for i in self.tree2.selection()]
        if not sel:
            messagebox.showinfo(self.t["heading"], self.t["dl_pick_first"])
            return
        dest = self.dest_var.get()
        target = INSTALL_DIR if dest.startswith("—") else INSTALL_DIR / dest
        target.mkdir(parents=True, exist_ok=True)
        self.log(self.t["log_sep"])
        self.log(self.t["dl_start"].format(n=len(sel), path=target))
        self.btn_dl.config(state="disabled")
        threading.Thread(target=self._dl_worker, args=(sel, target), daemon=True).start()

    def _dl_worker(self, sel, target):
        ok = fail = 0
        before = {f.name for f in target.iterdir()}
        for name, ident, ver in sel:
            self.q.put(f"\n⬇ {name} ({ident})")
            cmd = ["winget", "download", "--exact", "--id", ident, "-d", str(target),
                   "--accept-package-agreements", "--accept-source-agreements",
                   "--disable-interactivity"]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=600)
            except Exception as e:
                fail += 1
                self.q.put(self.t["err"].format(e=e))
                continue
            if r.returncode == 0:
                ok += 1
                new = sorted(f for f in target.iterdir() if f.name not in before)
                got = " · ".join(f"{f.name} ({fmt_size(f.stat().st_size)})" for f in new)
                self.q.put(self.t["dl_ok"].format(got=got or self.t["dl_ok_done"]))
                before = {f.name for f in target.iterdir()}
            else:
                fail += 1
                tail = "\n".join(decode_best((r.stderr or b"") + (r.stdout or b""))
                                 .splitlines()[-4:])
                self.q.put(self.t["dl_fail"].format(tail=tail))
        self.q.put(self.t["log_sep"])
        self.q.put(self.t["dl_summary"].format(ok=ok, fail=fail))
        self.q.put(self.t["dl_after"])
        self.after(0, lambda: self.btn_dl.config(state="normal"))


if __name__ == "__main__":
    if not INSTALL_DIR.exists():
        INSTALL_DIR.mkdir(parents=True)
    App().mainloop()