"""
Gomi as a desktop app: an icon in the system tray instead of a console window (user, 2026-10-23: "have
gomi be an app (or as a notification icon on my task bar) on my 2070box so I dont need to keep a console
open just for gomi ... be able to shut down gomi by the app too").

    venv/bin/python -m gomi.tray     (README, "Run"; the app-menu entry, gomihyu.desktop, runs this file)

Runs her (python -m gomi) as is, her console output going to data/gomi.log (earlier runs in data/logs/,
named by when they ended). Right-click the icon: "Open log" (the read lines for tuning the thresholds are
there now), "Shut down" (Ctrl+C: she writes her diary first; clicking again skips it). The icon goes once she's
stopped, however she stopped ("gomi goodnight" too), with a notification if she crashed; and she stops if
the tray goes.
"""

import ctypes
import fcntl
import signal
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOG = ROOT / "data" / "gomi.log"
PR_SET_PDEATHSIG = 1


def tray(app: QApplication, bot: subprocess.Popen) -> QSystemTrayIcon:
    """Her icon and its menu; quits the app once the bot has exited."""
    icon = QSystemTrayIcon(QIcon(str(HERE / "icon.png")))
    icon.setToolTip("Gomi")
    menu = QMenu()
    # xdg-open with her own environment, not QDesktopServices: pip Qt asks the desktop portal, and one woken
    # by a boot service before login has no display, so the editor it starts crashes (Nov 18, Nov 22).
    menu.addAction("Open log", lambda: QProcess.startDetached("xdg-open", [str(LOG)]))
    stop = menu.addAction("Shut down")

    def shut_down():
        bot.terminate()  # SIGTERM, which bot.py takes like Ctrl+C: a second one skips the diary
        stop.setText("Skip her diary and shut down")
        icon.setToolTip("Gomi: writing her diary, then shutting down")

    def check():
        if (code := bot.poll()) is None:
            return
        timer.stop()
        if code == 0:
            app.quit()
            return
        icon.showMessage("Gomi stopped", f"She crashed (exit code {code}): see {LOG}", QSystemTrayIcon.MessageIcon.Critical)
        QTimer.singleShot(5000, app.quit)  # time for the notification to go out

    stop.triggered.connect(shut_down)
    icon.setContextMenu(menu)
    icon.show()
    timer = QTimer(icon, timeout=check, interval=1000)
    timer.start()
    return icon


def main() -> None:
    lock = open(__file__)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # one Gomi: two would answer everything twice
    except BlockingIOError:
        sys.exit("Gomi's already running (her icon's in the tray)")
    LOG.parent.mkdir(exist_ok=True)
    if LOG.exists():
        # Every run's log is kept (Nov 24): one old copy held a day of room reads, too few to tune the thresholds.
        # shortcut: never pruned (~25KB a run), prune if data/logs/ ever gets big.
        old = LOG.parent / "logs" / time.strftime("gomi-%Y-%m-%d-%H%M%S.log", time.localtime(LOG.stat().st_mtime))
        old.parent.mkdir(exist_ok=True)
        LOG.replace(old)
    with open(LOG, "w") as out:
        # Started before Qt's threads; she gets SIGTERM (and writes her diary) if the tray dies or is killed.
        bot = subprocess.Popen([sys.executable, "-u", "-m", "gomi"], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=out,
                               stderr=subprocess.STDOUT,
                               preexec_fn=lambda: ctypes.CDLL(None).prctl(PR_SET_PDEATHSIG, signal.SIGTERM))
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    icon = tray(app, bot)  # held here: unreferenced, Python would delete her icon
    app.exec()


if __name__ == "__main__":
    main()
