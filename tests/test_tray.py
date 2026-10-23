import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# tray.py with a fake bot.py: Shut down sends SIGTERM (again: skip the diary), the tray quits when she exits
# (later after a crash), her output lands in gomi.log, a second tray won't start, killing the tray stops her.
import os, shutil, signal, subprocess, sys, time
from pathlib import Path
os.environ["QT_QPA_PLATFORM"] = "offscreen"
T = Path(TMP); shutil.copy(REPO + "/tray.py", T)
(T / "bot.py").write_text("""import os, signal, sys, time
print("Logged in as Gomihyu", flush=True)
if os.environ.get("FAKE_CRASH"): sys.exit(3)
terms = []
def term(*_):
    terms.append(1); open("marker", "a").write("diary\\n" if len(terms) == 1 else "skip\\n")
    if len(terms) == 2: sys.exit(0)
signal.signal(signal.SIGTERM, term)
while not terms: time.sleep(0.05)
time.sleep(2)  # "writing her diary": a second SIGTERM in here skips it
""")
sys.path.insert(0, TMP)
import tray
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
def fake(**env): return subprocess.Popen([sys.executable, "bot.py"], cwd=T, env=dict(os.environ, **env))
def wait_for(cond, secs=10):
    end = time.time() + secs
    while not cond() and time.time() < end: time.sleep(0.05)
    return cond()
marker = T / "marker"

bot = fake(); time.sleep(0.5)
icon = tray.tray(app, bot)
stop = [a for a in icon.contextMenu().actions() if a.text() == "Shut down"][0]
texts = []
QTimer.singleShot(100, lambda: (stop.trigger(), texts.append(stop.text())))
QTimer.singleShot(600, stop.trigger)
start = time.time(); app.exec()
assert bot.returncode == 0 and marker.read_text() == "diary\nskip\n", marker.read_text()
assert texts == ["Skip her diary and shut down"] and time.time() - start < 4
icon.hide(); marker.unlink()

bot = fake(); time.sleep(0.5)                                         # one click: she writes the diary, then quits
icon = tray.tray(app, bot); QTimer.singleShot(100, [a for a in icon.contextMenu().actions() if a.text() == "Shut down"][0].trigger)
app.exec()
assert bot.returncode == 0 and marker.read_text() == "diary\n"
icon.hide(); marker.unlink()

bot = fake(FAKE_CRASH="1")                                            # crash: notification, quits 5s later
icon = tray.tray(app, bot); start = time.time(); app.exec()
assert bot.returncode == 3 and 5 <= time.time() - start < 9
icon.hide()

(T / "gomi.log").write_text("the run before\n")                       # the real main(), as the app menu runs it
first = subprocess.Popen([sys.executable, str(T / "tray.py")])
assert wait_for(lambda: "Logged in" in (T / "gomi.log").read_text())
assert (T / "gomi.log.old").read_text() == "the run before\n"
second = subprocess.run([sys.executable, str(T / "tray.py")], capture_output=True, text=True, timeout=30)
assert second.returncode == 1 and "already running" in second.stderr, second
first.kill(); first.wait()                                            # the tray's gone: she still writes her diary
assert wait_for(lambda: marker.exists() and marker.read_text() == "diary\n")
print("TRAY TESTS PASSED")
