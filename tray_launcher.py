from __future__ import annotations

import argparse
import logging
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import psutil

pystray = None
Image = None
ImageDraw = None


HOST = "127.0.0.1"
PORT = 5000
DASHBOARD_URL = f"http://{HOST}:{PORT}"
POLL_SECONDS = 1.5


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT_DIR = _runtime_root()
DB_FILE = ROOT_DIR / "data" / "ponto.db"
LOG_FILE = ROOT_DIR / "data" / "launcher.log"


def _setup_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


@dataclass
class ProcInfo:
    pid: int
    name: str
    cmdline: str


class TrayLauncher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._child_process: subprocess.Popen | None = None
        self._last_state = ""
        self._icons = self._build_state_icons()

        self.icon = pystray.Icon(
            "ponto_tolentx",
            self._icons["off"],
            "PonTolentx",
            menu=pystray.Menu(
                pystray.MenuItem("Start", self._on_start_clicked),
                pystray.MenuItem("Stop", self._on_stop_clicked),
                pystray.MenuItem("Restart", self._on_restart_clicked),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Abrir Dashboard", self._on_open_dashboard_clicked),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Sair", self._on_exit_clicked),
            ),
        )

    def run(self) -> None:
        logging.info("Tray launcher started (pid=%s)", os.getpid())
        self.icon.run(setup=self._on_icon_ready)

    def _on_icon_ready(self, icon) -> None:
        icon.visible = True
        logging.info("Tray icon visible and ready")
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._bootstrap_startup, daemon=True).start()

    def _on_start_clicked(self, icon, item) -> None:
        threading.Thread(target=self._start_service, daemon=True).start()

    def _on_stop_clicked(self, icon, item) -> None:
        threading.Thread(target=self._stop_service, daemon=True).start()

    def _on_restart_clicked(self, icon, item) -> None:
        threading.Thread(target=self._restart_service, daemon=True).start()

    def _on_open_dashboard_clicked(self, icon, item) -> None:
        webbrowser.open(DASHBOARD_URL)

    def _on_exit_clicked(self, icon, item) -> None:
        self._stop_event.set()
        self.icon.stop()

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            self._refresh_icon_state()
            time.sleep(POLL_SECONDS)

    def _bootstrap_startup(self) -> None:
        # Auto-start service on launcher startup so shortcut click is enough to bring the app online.
        time.sleep(1.0)
        try:
            if self._is_port_listening():
                logging.info("Port %s already in use on startup; opening dashboard", PORT)
                webbrowser.open(DASHBOARD_URL)
                return
            logging.info("Auto-starting service on launcher startup")
            self._start_service()
        except Exception:
            logging.exception("Startup bootstrap failed")

    def _refresh_icon_state(self) -> None:
        state = self._resolve_state()
        if state == self._last_state:
            return

        self._last_state = state
        self.icon.icon = self._icons[state]
        if state == "off":
            self.icon.title = "PonTolentx - OFF"
        elif state == "online":
            self.icon.title = "PonTolentx - online (agendador parado)"
        else:
            self.icon.title = "PonTolentx - online (agendador ativo)"

    def _resolve_state(self) -> str:
        if not self._is_port_listening():
            return "off"
        return "running" if self._scheduler_is_active() else "online"

    def _start_service(self) -> None:
        logging.info("Start requested")
        with self._lock:
            busy = self._get_port_processes(PORT)
            if busy:
                logging.info("Start blocked: port %s busy: %s", PORT, self._format_process_list(busy))
                self._notify("Porta 5000 ja em uso", self._format_process_list(busy))
                return

            cmd = self._build_start_command()
            env = os.environ.copy()
            env["PTX_RUNTIME_DIR"] = str(ROOT_DIR)
            env["PTX_DISABLE_AUTO_BROWSER"] = "1"

            creation_flags = 0
            fallback_flags = 0
            if os.name == "nt":
                fallback_flags = subprocess.CREATE_NEW_PROCESS_GROUP
                creation_flags = fallback_flags
                creation_flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                creation_flags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)

            try:
                self._child_process = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT_DIR),
                    env=env,
                    creationflags=creation_flags,
                )
            except PermissionError:
                logging.warning("Advanced creation flags denied; retrying with fallback flags")
                self._child_process = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT_DIR),
                    env=env,
                    creationflags=fallback_flags,
                )
            logging.info("Service process spawned pid=%s", self._child_process.pid)

        if self._wait_until_port_is_listening(timeout=20):
            webbrowser.open(DASHBOARD_URL)
            self._notify("Servico iniciado", "Dashboard aberto no navegador.")
            logging.info("Service started and dashboard opened")
        else:
            self._notify("Falha ao iniciar", "Nao foi possivel subir o servico na porta 5000.")
            logging.error("Start failed: port %s not listening after timeout", PORT)

    def _stop_service(self) -> None:
        logging.info("Stop requested")
        with self._lock:
            targets = self._get_port_processes(PORT)
            if not targets and self._child_process and self._child_process.poll() is None:
                targets = [ProcInfo(self._child_process.pid, "service", "launcher child process")]

            if not targets:
                self._notify("Servico ja parado", "Nenhum processo ativo na porta 5000.")
                logging.info("Stop noop: no targets found")
                return

            target_pids = [p.pid for p in targets]
            stopped = self._terminate_processes(target_pids)
            port_is_free = self._wait_until_port_is_free(timeout=12)
            if not port_is_free:
                leftovers = self._get_port_processes(PORT)
                if leftovers:
                    stopped.extend(self._terminate_processes([p.pid for p in leftovers]))
                port_is_free = self._wait_until_port_is_free(timeout=6)
            self._child_process = None

        if stopped and port_is_free:
            self._notify("Stop concluido", f"PIDs encerrados: {', '.join(str(pid) for pid in stopped)}")
            logging.info("Stop completed. PIDs=%s", stopped)
        elif port_is_free:
            self._notify("Stop concluido", "Sinal enviado aos processos da porta 5000.")
            logging.info("Stop completed without confirmed PID termination")
        else:
            self._notify("Stop parcial", "A porta 5000 ainda esta ocupada apos o stop.")
            logging.warning("Stop partial: port %s still busy", PORT)

    def _restart_service(self) -> None:
        logging.info("Restart requested")
        self._stop_service()
        time.sleep(0.8)
        self._start_service()

    @staticmethod
    def _build_start_command() -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--service"]
        return [sys.executable, str(Path(__file__).resolve()), "--service"]

    @staticmethod
    def _is_port_listening() -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            return sock.connect_ex((HOST, PORT)) == 0

    @staticmethod
    def _wait_until_port_is_listening(timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if TrayLauncher._is_port_listening():
                return True
            time.sleep(0.25)
        return False

    @staticmethod
    def _wait_until_port_is_free(timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not TrayLauncher._is_port_listening():
                return True
            time.sleep(0.25)
        return False

    @staticmethod
    def _scheduler_is_active() -> bool:
        if not DB_FILE.exists():
            return False
        try:
            with sqlite3.connect(DB_FILE, timeout=1) as conn:
                row = conn.execute(
                    "SELECT value FROM config WHERE key = 'scheduler_active'"
                ).fetchone()
            return bool(row and row[0] == "1")
        except sqlite3.Error:
            return False

    @staticmethod
    def _get_port_processes(port: int) -> list[ProcInfo]:
        pids: set[int] = set()
        try:
            for conn in psutil.net_connections(kind="inet"):
                if not conn.laddr or conn.laddr.port != port:
                    continue
                if conn.pid is not None:
                    pids.add(conn.pid)
        except Exception:
            return []

        results: list[ProcInfo] = []
        for pid in sorted(pids):
            if pid in (0, os.getpid()):
                continue
            try:
                proc = psutil.Process(pid)
                cmdline = " ".join(proc.cmdline()) or proc.name()
                results.append(ProcInfo(pid=pid, name=proc.name(), cmdline=cmdline))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return results

    @staticmethod
    def _terminate_processes(pids: list[int]) -> list[int]:
        candidates: list[psutil.Process] = []
        for pid in sorted(set(pids)):
            if pid in (0, os.getpid()):
                continue
            try:
                candidates.append(psutil.Process(pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        for proc in candidates:
            try:
                proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        _, alive = psutil.wait_procs(candidates, timeout=4)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        stopped: list[int] = []
        for proc in candidates:
            try:
                if not proc.is_running():
                    stopped.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                stopped.append(proc.pid)
        return stopped

    @staticmethod
    def _format_process_list(items: list[ProcInfo]) -> str:
        compact = []
        for item in items:
            cmd = item.cmdline.strip() or item.name
            if len(cmd) > 48:
                cmd = cmd[:45] + "..."
            compact.append(f"PID {item.pid} ({item.name}) {cmd}")
        text = "; ".join(compact)
        if len(text) > 220:
            return text[:217] + "..."
        return text

    def _notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:
            print(f"[{title}] {message}")

    @staticmethod
    def _build_state_icons() -> dict[str, object]:
        off = TrayLauncher._draw_icon((218, 74, 74), with_play=False)
        online = TrayLauncher._draw_icon((40, 167, 69), with_play=False)
        running = TrayLauncher._draw_icon((40, 167, 69), with_play=True)
        return {"off": off, "online": online, "running": running}

    @staticmethod
    def _draw_icon(base_color: tuple[int, int, int], with_play: bool):
        size = 64
        icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon)
        draw.ellipse((4, 4, size - 4, size - 4), fill=base_color, outline=(22, 22, 22), width=2)

        if with_play:
            triangle = [(24, 19), (24, 45), (45, 32)]
            draw.polygon(triangle, fill=(255, 255, 255))
        return icon


def run_service_mode() -> None:
    _setup_logging()
    logging.info("Service mode entered")
    os.environ["PTX_RUNTIME_DIR"] = str(ROOT_DIR)
    os.environ["PTX_DISABLE_AUTO_BROWSER"] = "1"

    import app as web_app

    web_app.run_server(open_browser=False)


def _import_tray_dependencies() -> bool:
    global pystray, Image, ImageDraw
    try:
        import pystray as _pystray
        from PIL import Image as _Image, ImageDraw as _ImageDraw
    except Exception:
        logging.exception("Tray dependencies failed to import")
        return False

    pystray = _pystray
    Image = _Image
    ImageDraw = _ImageDraw
    return True


def run_tray_mode() -> None:
    _setup_logging()
    if not _import_tray_dependencies():
        logging.error("Falling back to service-only mode")
        threading.Thread(
            target=lambda: (time.sleep(1.5), webbrowser.open(DASHBOARD_URL)),
            daemon=True,
        ).start()
        run_service_mode()
        return
    try:
        launcher = TrayLauncher()
        logging.info("TrayLauncher created, calling icon.run()")
        launcher.run()
    except Exception:
        logging.exception("Tray icon failed — falling back to service-only mode")
        run_service_mode()


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--service", action="store_true")
    args, _ = parser.parse_known_args()

    if args.service:
        run_service_mode()
        return

    run_tray_mode()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _setup_logging()
        logging.exception("Fatal launcher error")
        raise
