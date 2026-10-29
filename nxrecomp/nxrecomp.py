"""NX Recomp Hub: one window for every way this PC can run a Switch game.

For each game in the ROM folder it shows what each project can do with it on this hardware:
  - UltraTears  (static recompilation ARM64 -> C -> x86-64, Windows + Vulkan): Tears of the Kingdom 1.4.3 only
  - nxnative    (native ARM64 execution, Metal): needs an Apple Silicon Mac / iPhone 15 Pro+ / M1 iPad
  - Lift test   (UltraTears' lifter on any game's code): translates the game's ARM64 code to C, the first stage
                of a port; there is no runtime for it yet, so it does not produce something playable
  - Emulator    (Eden / Ryujinx / Sudachi found on this PC): the way to play everything else today

Decryption uses nxnative's nx_extract (LibHac) with the player's own prod.keys. Everything this tool writes stays
under the project folder (work\\, .cache\\); nothing goes to C:.
"""
import ctypes, json, os, queue, re, shutil, struct, subprocess, sys, threading, time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONFIG = HERE / 'config.json'
NX_EXTRACT = HERE / 'bin/nx_extract/nx_extract.exe'
REFS = ROOT / 'refs'
VENV_PY = ROOT / '.venv/Scripts/python.exe'
CACHE = ROOT / '.cache'

TOTK = '0100F2C0115B6000'
TOTK_VERSION = 720896          # update 1.4.3, the only one UltraTears accepts
LIFT_BASE = 0x0800000000       # where UltraTears maps main (tools/gen_game.py)

DEFAULTS = {
    'keys': r'T:\Emulation\Switch Keys\prod.keys',
    'roms': r'T:\Emulation\Roms\Switch',
    'filesystem': r'T:\Emulation\Switch file system',
    'work': str(ROOT / 'work'),
    'emulators': {
        'Eden': r'T:\Emulation\Eden\eden.exe',
        'Ryujinx': r'T:\Emulation\Ryujinx\Ryujinx.exe',
        'Sudachi': r'T:\Emulation\Sudachi\sudachi.exe',
    },
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG.is_file():
        try:
            cfg.update(json.loads(CONFIG.read_text(encoding='utf-8')))
        except ValueError:
            pass
    return cfg


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding='utf-8')


def tool_env():
    """Point every temp/cache folder of the tools we start at the project's .cache (keeps C: untouched)."""
    env = dict(os.environ)
    for sub in ('tmp', 'pip', 'nuget', 'dotnet', 'pycache'):
        (CACHE / sub).mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(CACHE / 'tmp'), TMP=str(CACHE / 'tmp'), PIP_CACHE_DIR=str(CACHE / 'pip'),
               NUGET_PACKAGES=str(CACHE / 'nuget'), DOTNET_CLI_HOME=str(CACHE / 'dotnet'),
               PYTHONPYCACHEPREFIX=str(CACHE / 'pycache'), DOTNET_CLI_TELEMETRY_OPTOUT='1',
               DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1', PYTHONUNBUFFERED='1', PYTHONNOUSERSITE='1')
    return env


# ---------------------------------------------------------------- library scan
TID_RE = re.compile(r'\[([0-9A-Fa-f]{16})\]')
VER_RE = re.compile(r'\[v(\d+)\]')
VER_BARE_RE = re.compile(r'\[(\d{5,10})\]')   # "[65536]" without the v; never a 16-digit title ID
PACKAGES = ('.nsp', '.xci', '.nsz', '.xcz')


def pfs0_ticket_tid(path):
    """Title ID of an NSP named without one: from its ticket's name (rights ID = title ID + key generation), or from
    the plain-text cnmt.xml that ticketless (standard crypto) NSPs carry."""
    try:
        with open(path, 'rb') as f:
            h = f.read(16)
            if h[:4] != b'PFS0':
                return None
            n, strsize = struct.unpack_from('<II', h, 4)
            table = f.read(n * 0x18)
            strings = f.read(strsize)
            data = 16 + n * 0x18 + strsize
            for i in range(n):
                off, size, name_off = struct.unpack_from('<QQI', table, i * 0x18)
                name = strings[name_off:strings.find(b'\0', name_off)].decode('ascii', 'ignore').lower()
                if name.endswith('.tik') and len(name) >= 36:
                    return name[:16].upper()
                if name.endswith('.cnmt.xml') and size < 1 << 20:
                    f.seek(data + off)
                    m = re.search(rb'<Id>0x([0-9a-fA-F]{16})</Id>', f.read(size))
                    if m:
                        return m.group(1).decode().upper()
    except (OSError, struct.error):
        pass
    return None


def kind_of(tid):
    low = int(tid, 16) & 0xFFF
    if low == 0:
        return 'base'
    if low == 0x800:
        return 'update'
    return 'dlc'


def base_of(tid):
    t = int(tid, 16)
    low = t & 0xFFF
    if low == 0x800:
        t &= ~0xFFF
    elif low:
        t = (t & ~0xFFF) - 0x1000
    return f'{t:016X}'


class Game:
    def __init__(self, tid):
        self.tid = tid
        self.name = None
        self.base = None
        self.updates = []      # (version or -1, path)
        self.dlc = []
        self.folder = None

    @property
    def update(self):
        if not self.updates:
            return None
        return max(self.updates, key=lambda u: (u[0], u[1].name))   # unnamed versions: "Update 1.0.2" > "Update 1.0.1"

    @property
    def version(self):
        u = self.update
        if not u:
            return 0
        return u[0]

    def label_version(self):
        u = self.update
        if not u:
            return 'v0 (base)'
        return f'v{u[0]}' if u[0] >= 0 else 'update (version unknown)'


def scan(roms):
    games = {}
    for p in sorted(Path(roms).rglob('*')):
        if p.suffix.lower() not in PACKAGES or not p.is_file():
            continue
        m = TID_RE.search(p.name)
        tid = m.group(1).upper() if m else (pfs0_ticket_tid(p) if p.suffix.lower() == '.nsp' else None)
        if not tid:
            continue
        vm = VER_RE.search(p.name) or VER_BARE_RE.search(p.name)
        ver = int(vm.group(1)) if vm else (0 if kind_of(tid) == 'base' else -1)
        g = games.setdefault(base_of(tid), Game(base_of(tid)))
        g.folder = g.folder or p.parent
        k = kind_of(tid)
        if k == 'base':
            g.base = p
            g.name = g.name or re.split(r'\s*\[', p.stem)[0].strip() or p.parent.name
        elif k == 'update':
            g.updates.append((ver, p))
        else:
            g.dlc.append(p)
    for g in games.values():
        g.name = g.name or (g.folder.name if g.folder else g.tid)
    return sorted((g for g in games.values() if g.base), key=lambda g: g.name.lower())


def is_32bit(npdm):
    """main.npdm's META flags bit 0 clear = an AArch32 program (Pikmin 3 Deluxe), which no ARM64 tool handles."""
    try:
        d = Path(npdm).read_bytes()
        return d[:4] == b'META' and not d[0xC] & 1
    except OSError:
        return False


def game_ports():
    """ports/<name>/ trees (UltraTears copies adapted to one game): title ID (from its PORTING.md) -> folder."""
    out = {}
    for doc in (ROOT / 'ports').glob('*/PORTING.md'):
        m = re.search(r'\b(0100[0-9A-Fa-f]{12})\b', doc.read_text(encoding='utf-8', errors='ignore'))
        if m:
            out[m.group(1).upper()] = doc.parent
    return out


def nxnative_profiles():
    out = {}
    d = REFS / 'nxnative/dm/games'
    for tsv in d.glob('*/game.tsv'):
        info = {'package': None, 'versions': {}}
        for line in tsv.read_text(encoding='utf-8', errors='ignore').splitlines():
            parts = line.split('\t')
            if parts[0] == 'name' and len(parts) > 1:
                info['name'] = parts[1]
            elif parts[0] == 'package' and len(parts) > 1:
                info['package'] = parts[1]
            elif parts[0] == 'build' and len(parts) > 2:
                info['versions'][parts[1]] = parts[2]
        out[tsv.parent.name.upper()] = info
    return out


# ---------------------------------------------------------------- hardware
def hardware():
    hw = {}
    try:
        hw['avx2'] = bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))   # PF_AVX2_INSTRUCTIONS_AVAILABLE
    except Exception:
        hw['avx2'] = None
    hw['arch'] = os.environ.get('PROCESSOR_ARCHITECTURE', '?')

    class MEM(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                    ('avail', ctypes.c_ulonglong), ('a', ctypes.c_ulonglong), ('b', ctypes.c_ulonglong),
                    ('c', ctypes.c_ulonglong), ('d', ctypes.c_ulonglong), ('e', ctypes.c_ulonglong)]
    m = MEM(); m.len = ctypes.sizeof(MEM)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        hw['ram_gb'] = round(m.total / 2**30)
    except Exception:
        hw['ram_gb'] = None
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0')
        hw['cpu'] = winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip()
    except Exception:
        hw['cpu'] = '?'
    hw['gpu'], hw['vk_api'], hw['shader_object'] = '?', '?', None
    vk = shutil.which('vulkaninfo')
    if vk:
        try:
            s = subprocess.run([vk, '--summary'], capture_output=True, text=True, timeout=30,
                               creationflags=0x08000000).stdout
            names = re.findall(r'deviceName\s*=\s*(.+)', s)
            apis = re.findall(r'apiVersion\s*=\s*(\S+)', s)
            real = [i for i, n in enumerate(names) if 'llvmpipe' not in n.lower()]
            if real:
                hw['gpu'], hw['vk_api'] = names[real[0]].strip(), apis[real[0]] if len(apis) > real[0] else '?'
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW   # hidden; CREATE_NO_WINDOW hangs it
            full = subprocess.run([vk], capture_output=True, stdin=subprocess.DEVNULL, timeout=90, startupinfo=si).stdout
            hw['shader_object'] = b'VK_EXT_shader_object' in full
        except Exception:
            pass
    return hw


# ---------------------------------------------------------------- the window
class App(tk.Tk):
    COLS = ('version', 'pc', 'apple', 'lift', 'emu')

    def __init__(self):
        super().__init__()
        self.title('NX Recomp Hub')
        self.geometry('1280x780')
        self.minsize(980, 600)
        self.cfg = load_config()
        self.jobs = queue.Queue()
        self.log_q = queue.Queue()
        self.busy = False
        self.proc = None
        self.games = []
        self.profiles = nxnative_profiles()
        self.ports = game_ports()
        self.hw = {}
        self._build()
        threading.Thread(target=self._worker, daemon=True).start()
        self.after(100, self._pump_log)
        self.rescan()
        threading.Thread(target=self._detect_hw, daemon=True).start()

    # --- layout
    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use('vista')
        except tk.TclError:
            pass
        top = ttk.Frame(self, padding=(10, 8)); top.pack(fill='x')
        self.paths = {}
        for i, (key, label) in enumerate((('keys', 'prod.keys'), ('roms', 'ROM folder'),
                                          ('filesystem', 'Switch file system'), ('work', 'Work folder'))):
            ttk.Label(top, text=label).grid(row=i // 2, column=(i % 2) * 3, sticky='w', padx=(0, 6), pady=2)
            v = tk.StringVar(value=self.cfg[key]); self.paths[key] = v
            ttk.Entry(top, textvariable=v, width=52).grid(row=i // 2, column=(i % 2) * 3 + 1, sticky='we', pady=2)
            ttk.Button(top, text='…', width=3, command=lambda k=key: self._browse(k)).grid(
                row=i // 2, column=(i % 2) * 3 + 2, padx=(2, 14))
        top.columnconfigure(1, weight=1); top.columnconfigure(4, weight=1)

        self.hw_var = tk.StringVar(value='Checking hardware…')
        ttk.Label(self, textvariable=self.hw_var, padding=(10, 0), foreground='#555').pack(fill='x')

        body = ttk.PanedWindow(self, orient='vertical'); body.pack(fill='both', expand=True, padx=10, pady=6)
        upper = ttk.PanedWindow(body, orient='horizontal'); body.add(upper, weight=3)

        tf = ttk.Frame(upper); upper.add(tf, weight=3)
        self.tree = ttk.Treeview(tf, columns=self.COLS, show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='Game'); self.tree.column('#0', width=280)
        for c, t, w in (('version', 'Your version', 120), ('pc', 'Native on this PC', 170),
                        ('apple', 'Native on Apple', 150), ('lift', 'Lift test', 130), ('emu', 'Emulator', 90)):
            self.tree.heading(c, text=t); self.tree.column(c, width=w, anchor='w')
        sb = ttk.Scrollbar(tf, orient='vertical', command=self.tree.yview); self.tree.configure(yscroll=sb.set)
        self.tree.pack(side='left', fill='both', expand=True); sb.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._show_details())
        self.tree.bind('<Double-1>', lambda e: self.play())
        for tag, col in (('ready', '#0a7d2c'), ('blocked', '#a05a00'), ('none', '#777')):
            self.tree.tag_configure(tag, foreground=col)

        side = ttk.Frame(upper, padding=(10, 0)); upper.add(side, weight=2)
        self.detail = tk.Text(side, wrap='word', height=14, relief='flat', bg=self.cget('bg'), font=('Segoe UI', 10))
        self.detail.pack(fill='both', expand=True)
        btns = ttk.Frame(side); btns.pack(fill='x', pady=(6, 0))
        self.b_play = ttk.Button(btns, text='▶ Play (best available)', command=self.play)
        self.b_extract = ttk.Button(btns, text='Decrypt game (ExeFS + RomFS)', command=lambda: self.extract(full=True))
        self.b_lift = ttk.Button(btns, text='Recompile test: lift code to C', command=self.lift)
        self.b_compile = ttk.Button(btns, text='Compile test: lifted C → x86-64 objects', command=self.compile_test)
        self.b_native = ttk.Button(btns, text='Build native PC port (UltraTears)', command=self.build_native)
        self.b_port = ttk.Button(btns, text='Run native port (experimental)', command=self.run_port)
        self.b_folder = ttk.Button(btns, text='Open work folder', command=self.open_work)
        for b in (self.b_play, self.b_extract, self.b_lift, self.b_compile, self.b_native, self.b_port, self.b_folder):
            b.pack(fill='x', pady=2)
        emu = ttk.Frame(btns); emu.pack(fill='x', pady=(8, 0))
        ttk.Label(emu, text='Emulator:').pack(side='left')
        self.emu_var = tk.StringVar(value=next(iter(self._emulators()), ''))
        self.emu_box = ttk.Combobox(emu, textvariable=self.emu_var, state='readonly', width=12,
                                    values=list(self._emulators()))
        self.emu_box.pack(side='left', padx=6)
        ttk.Button(emu, text='Launch in emulator', command=self.play_emulator).pack(side='left', fill='x', expand=True)

        lf = ttk.Frame(body); body.add(lf, weight=2)
        bar = ttk.Frame(lf); bar.pack(fill='x')
        self.status = tk.StringVar(value='Idle')
        ttk.Label(bar, textvariable=self.status).pack(side='left')
        ttk.Button(bar, text='Stop job', command=self.stop).pack(side='right')
        ttk.Button(bar, text='Rescan', command=self.rescan).pack(side='right', padx=6)
        self.log = tk.Text(lf, height=10, wrap='none', bg='#111', fg='#ddd', insertbackground='#ddd',
                           font=('Consolas', 9))
        ls = ttk.Scrollbar(lf, orient='vertical', command=self.log.yview); self.log.configure(yscroll=ls.set)
        self.log.pack(side='left', fill='both', expand=True); ls.pack(side='right', fill='y')

    def _browse(self, key):
        p = filedialog.askopenfilename() if key == 'keys' else filedialog.askdirectory()
        if p:
            self.paths[key].set(os.path.normpath(p)); self._save()

    def _save(self):
        for k, v in self.paths.items():
            self.cfg[k] = v.get()
        save_config(self.cfg)

    def _emulators(self):
        return {n: p for n, p in self.cfg.get('emulators', {}).items() if Path(p).is_file()}

    def _detect_hw(self):
        hw = hardware(); self.hw = hw
        free = shutil.disk_usage(Path(self.cfg['work']).anchor).free / 2**30
        ok = lambda b: '✔' if b else ('?' if b is None else '✘')
        txt = (f"{hw['cpu']} ({hw['arch']}) · AVX2 {ok(hw['avx2'])} · {hw['ram_gb']} GB RAM · {hw['gpu']} · "
               f"Vulkan {hw['vk_api']} · shader_object {ok(hw['shader_object'])} · {free:.0f} GB free on "
               f"{Path(self.cfg['work']).anchor}  —  UltraTears: "
               f"{'supported' if hw['avx2'] and hw['shader_object'] else 'check failed'}; nxnative: "
               f"{'needs Apple Silicon (this is x86-64)' if hw['arch'] != 'ARM64' else 'needs macOS/iOS'}")
        self._ui(self.hw_var.set, txt)

    # --- library
    def rescan(self):
        self._save()
        roms = self.cfg['roms']
        if not Path(roms).is_dir():
            messagebox.showerror('NX Recomp Hub', f'ROM folder not found: {roms}'); return
        self.games = scan(roms)
        self.tree.delete(*self.tree.get_children())
        emus = bool(self._emulators())
        for g in self.games:
            pc, apple, lift = self._status(g)
            tag = 'ready' if pc.startswith('✔') else 'blocked' if pc.startswith('⚠') else 'none'
            self.tree.insert('', 'end', iid=g.tid, text=g.name, tags=(tag,),
                             values=(g.label_version(), pc, apple, lift, '✔' if emus else '—'))
        self._log(f'Library: {len(self.games)} games in {roms}\n')
        if self.games:
            self.tree.selection_set(self.games[0].tid)

    def _work(self, g):
        return Path(self.cfg['work']) / g.tid

    def _status(self, g):
        if g.tid == TOTK:
            built = (self._work(g) / 'ultratears/UltraTears.exe').is_file()
            pc = '✔ built' if built else ('✔ ready to build' if g.version == TOTK_VERSION
                                          else '⚠ needs update 1.4.3')
        elif g.tid in self.ports:
            pc = '⚙ port in progress' + (', built' if (self.ports[g.tid] / 'UltraTears.exe').is_file() else '')
        else:
            pc = '— no port yet'
        prof = self.profiles.get(g.tid)
        apple = f"✔ profile ({prof['versions'].get(prof['package'], prof['package'])})" if prof else '—'
        log = self._work(g) / 'lift/summary.json'
        if is_32bit(self._work(g) / 'extract/ExeFS/main.npdm'):
            lift = '✘ 32-bit ARM'
        elif log.is_file():
            s = json.loads(log.read_text())
            lift = f"✔ {s.get('functions', '?')} functions"
            objs = self._work(g) / 'build/obj'
            if objs.is_dir():
                n = sum(1 for _ in objs.rglob('*.o'))
                lift += ', compiled' if n >= s.get('c_files', 1 << 30) else f', {n} objects'
        else:
            lift = 'not run'
        return pc, apple, lift

    def _sel(self):
        s = self.tree.selection()
        return next((g for g in self.games if g.tid == s[0]), None) if s else None

    def _show_details(self):
        g = self._sel()
        if not g:
            return
        prof = self.profiles.get(g.tid)
        lines = [g.name, f'Title ID {g.tid} · {g.label_version()} · {len(g.dlc)} DLC', f'Base: {g.base.name}']
        if g.update:
            lines.append(f'Update: {g.update[1].name}')
        lines.append('')
        if g.tid == TOTK:
            if g.version == TOTK_VERSION:
                lines.append('Native PC: UltraTears can build this. Decrypt, then "Build native PC port" '
                             '(about 35 min, 32 GB in the work folder).')
            else:
                lines.append(f'Native PC: UltraTears needs update 1.4.3 (v{TOTK_VERSION}); you have '
                             f'{g.label_version()}. Dump 1.4.3 from your console into this folder.')
        elif g.tid in self.ports:
            lines.append(f'Native PC: an experimental port is in {self.ports[g.tid]} (status in its PORTING.md). '
                         '"Run native port" boots it with a window; it does not reach gameplay yet.')
        else:
            lines.append('Native PC: no Windows port of this game exists yet. "Recompile test" runs the '
                         'UltraTears lifter on its code (step one of a port); playing needs a runtime that '
                         'does not exist for this game.')
        if prof:
            want = prof['versions'].get(prof['package'], prof['package'])
            lines.append(f"Native Apple: nxnative supports it ({prof['package']} = {want}). Runs on an Apple Silicon "
                         'Mac, iPhone 15 Pro+ or M1 iPad, built on a Mac — not on this PC.')
        else:
            lines.append('Native Apple: no nxnative profile.')
        emus = ', '.join(self._emulators()) or 'none found'
        lines.append(f'Play today: emulator ({emus}).')
        self.detail.configure(state='normal'); self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', '\n'.join(lines)); self.detail.configure(state='disabled')
        self.b_native.state(['!disabled'] if g.tid == TOTK and g.version == TOTK_VERSION else ['disabled'])
        self.b_port.state(['!disabled'] if g.tid in self.ports else ['disabled'])

    # --- jobs
    def _log(self, s):
        self.log_q.put(s)

    def _ui(self, fn, *args):   # from worker threads: Tk may only be touched by the main thread
        self.log_q.put((fn, args))

    def _pump_log(self):
        try:
            while True:
                s = self.log_q.get_nowait()
                if isinstance(s, tuple):
                    s[0](*s[1])
                else:
                    self.log.insert('end', s); self.log.see('end')
        except queue.Empty:
            pass
        self.after(100, self._pump_log)

    def _worker(self):
        while True:
            title, fn = self.jobs.get()
            self.busy = True; self._ui(self.status.set, f'Running: {title}')
            t0 = time.time()
            try:
                fn()
                self._log(f'== {title}: done in {time.time() - t0:.0f} s\n')
            except Exception as e:
                self._log(f'== {title}: FAILED — {e}\n')
            self.busy = False; self.proc = None
            self._ui(self.status.set, 'Idle')
            self._ui(self._refresh_row)

    def _refresh_row(self):
        g = self._sel()
        for game in self.games:
            pc, apple, lift = self._status(game)
            vals = list(self.tree.item(game.tid, 'values')); vals[1:4] = pc, apple, lift
            self.tree.item(game.tid, values=vals)
        if g:
            self._show_details()

    def _queue(self, title, fn):
        self._save()
        self._log(f'== {title}: queued\n')
        self.jobs.put((title, fn))

    def _run(self, cmd, cwd=None, log_file=None, env=None):
        self._log('$ ' + ' '.join(f'"{c}"' if ' ' in str(c) else str(c) for c in cmd) + '\n')
        fh = open(log_file, 'w', encoding='utf-8') if log_file else None
        self.proc = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env or tool_env(), stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                     creationflags=0x08000000)
        out = []
        for line in self.proc.stdout:
            out.append(line); self._log(line)
            if fh:
                fh.write(line)
        rc = self.proc.wait()
        if fh:
            fh.close()
        if rc:
            raise RuntimeError(f'exit code {rc}')
        return ''.join(out)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate(); self._log('== stopped by user\n')

    # --- actions
    def extract(self, full, g=None, then=None):
        g = g or self._sel()
        if not g:
            return
        keys = self.cfg['keys']
        if not Path(keys).is_file():
            messagebox.showerror('NX Recomp Hub', f'prod.keys not found: {keys}'); return
        out = self._work(g) / 'extract'

        def job():
            done = (out / 'ExeFS/main').is_file() and (not full or (out / 'RomFS').is_dir())
            if done:
                self._log(f'already extracted: {out}\n')
            else:
                upd = g.update[1] if g.update else '-'
                if full and (out / 'RomFS').exists():
                    shutil.rmtree(out / 'RomFS')
                self._run([NX_EXTRACT, keys, g.base, upd, out] + ([] if full else ['--manifest']))
            if then:
                then()
        self._queue(f'decrypt {g.name}' + ('' if full else ' (code only)'), job)

    def lift(self):
        g = self._sel()
        if not g:
            return
        w = self._work(g)

        def job():
            if not (w / 'extract/ExeFS/main').is_file():
                self._run([NX_EXTRACT, self.cfg['keys'], g.base, g.update[1] if g.update else '-', w / 'extract',
                           '--manifest'])
            if is_32bit(w / 'extract/ExeFS/main.npdm'):
                raise RuntimeError(f'{g.name} is a 32-bit ARM (AArch32) program: the lifter translates ARM64 only, '
                                   'and nxnative cannot run it either. Play it in an emulator.')
            lifter = REFS / 'ultratears/tools/lifter/gen.py' if g.tid == TOTK and g.version == TOTK_VERSION \
                else HERE / 'lift_generic.py'
            if (w / 'lift/main').is_dir():
                shutil.rmtree(w / 'lift/main')
            out = self._run([VENV_PY, lifter, 'main',
                             w / 'extract/ExeFS/main', hex(LIFT_BASE), w / 'lift/main'], log_file=w / 'lift_main.log')
            m = re.search(r'(\d+) functions', out)
            files = list((w / 'lift/main').glob('*.c'))
            size = sum(f.stat().st_size for f in files)
            summary = {'functions': int(m.group(1)) if m else None, 'c_files': len(files),
                       'c_mb': round(size / 2**20), 'when': time.strftime('%Y-%m-%d %H:%M')}
            (w / 'lift/summary.json').write_text(json.dumps(summary))
            self._log(f"lifted main: {summary['functions']} functions → {summary['c_files']} C files, "
                      f"{summary['c_mb']} MB in {w / 'lift/main'}\n")
        self._queue(f'lift {g.name}', job)

    def compile_test(self):
        g = self._sel()
        if not g:
            return
        w = self._work(g)
        if not (w / 'lift/summary.json').is_file():
            messagebox.showinfo('NX Recomp Hub', 'Run the recompile test (lift) first.'); return
        self._queue(f'compile {g.name}', lambda: self._run(
            [VENV_PY, HERE / 'compile_lift.py', w, '-j', max(1, (os.cpu_count() or 4) - 2)], log_file=w / 'compile.log'))

    def run_port(self):
        """Build the game's port incrementally and boot it in a window; its log goes to <port>/run/hub.log."""
        g = self._sel()
        if not g or g.tid not in self.ports:
            return
        port, w = self.ports[g.tid], self._work(g)
        if not (w / 'extract/RomFS').is_dir():
            messagebox.showinfo('NX Recomp Hub', 'Decrypt the game first (it needs the RomFS).'); return

        def job():
            env = tool_env()
            env['ULTRS_CLANG64'] = str(REFS / 'ultratears/deps/clang64/bin')
            self._run([VENV_PY, port / 'tools/build_game.py', '--generated', os.path.relpath(w / 'lift', port),
                       '--target', 'ultratears', '--cpus', max(1, (os.cpu_count() or 4) - 2)], cwd=port, env=env)
            (port / 'run').mkdir(exist_ok=True)
            # shaders the port has no translation for are captured while it runs and translated after it exits,
            # so each session fills in more of the game (Unreal keeps its shaders in its pak, out of reach at build time)
            shaders = w / 'shaders'
            (shaders / 'ryujinx').mkdir(parents=True, exist_ok=True)
            env.update(TOTK_ROMFS=str(w / 'extract/RomFS'), TOTK_PROFILE_DIR=str(port / 'run/saves'),
                       TOTK_SHADER_CAPTURE=str(shaders), TOTK_SHADER_DIR=str(shaders / 'ryujinx'))
            with open(port / 'run/hub.log', 'w', encoding='utf-8') as log:
                rc = subprocess.run([str(port / 'UltraTears.exe'), str(w / 'extract/ExeFS')], cwd=port, env=env,
                                    stdout=log, stderr=subprocess.STDOUT).returncode
            tail = (port / 'run/hub.log').read_text(encoding='utf-8', errors='replace').splitlines()[-12:]
            self._log('\n'.join(tail) + f'\nport exited with {rc} (full log: {port / "run/hub.log"})\n')
            if (shaders / 'raw').is_dir():
                self._run([VENV_PY, HERE / 'shaders_from_capture.py', shaders], env=tool_env())
        self._queue(f'run port {g.name}', job)

    def build_native(self):
        g = self._sel()
        if not g or g.tid != TOTK:
            return
        if g.version != TOTK_VERSION:
            messagebox.showwarning('NX Recomp Hub', f'UltraTears needs Tears of the Kingdom 1.4.3 (v{TOTK_VERSION}).')
            return
        w = self._work(g)

        def build():
            self._run([VENV_PY, REFS / 'ultratears/tools/setup.py', '--output', w / 'ultratears',
                       '--dump', w / 'extract'], cwd=REFS / 'ultratears')
        self.extract(full=True, g=g, then=build)

    def play(self):
        g = self._sel()
        if not g:
            return
        exe = self._work(g) / 'ultratears/UltraTears.exe'
        if g.tid == TOTK and exe.is_file():
            subprocess.Popen([str(exe)], cwd=exe.parent, env=tool_env())
            self._log(f'started native {exe}\n')
        else:
            self.play_emulator()

    def play_emulator(self):
        g = self._sel()
        emus = self._emulators()
        if not g or not emus:
            messagebox.showinfo('NX Recomp Hub', 'No emulator found. Set paths in nxrecomp\\config.json.'); return
        name = self.emu_var.get() or next(iter(emus))
        exe = emus[name]
        cmd = [exe, '-g', str(g.base)] if name in ('Eden', 'Sudachi') else [exe, str(g.base)]
        subprocess.Popen(cmd, cwd=Path(exe).parent)
        self._log(f'started {name}: {g.name}' + (f' (install update {g.update[1].name} in {name} if it is '
                                                 'not installed yet)' if g.update else '') + '\n')

    def open_work(self):
        g = self._sel()
        p = self._work(g) if g else Path(self.cfg['work'])
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(p)


if __name__ == '__main__':
    App().mainloop()
