# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from Settings import console


# One background service: the name shown in the console and the command line that starts it.
@dataclass(frozen=True)
class ServiceSpec:
    name: str
    args: tuple[str, ...]


# Run background services as child processes: start them together with the site, print their output
# to the shared console with the service name, restart a service that exits on its own and stop all
# of them on shutdown.
class ServiceSupervisor:
    # Delay before the first restart; it doubles for a service that keeps failing, up to the cap.
    RESTART_DELAY_SECONDS = 2.0
    MAX_RESTART_DELAY_SECONDS = 60.0
    # A service that ran at least this long before exiting restarts with the initial delay again.
    STABLE_RUN_SECONDS = 60.0
    # Time a service gets to exit after the stop request before it is killed.
    STOP_TIMEOUT_SECONDS = 10.0
    POLL_INTERVAL_SECONDS = 0.5

    def __init__(self, services: list[ServiceSpec], *, cwd: Path | None = None, log: bool = False) -> None:
        self._services = list(services)
        self._cwd = cwd
        self._log = log
        self._processes: dict[str, subprocess.Popen] = {}
        self._relays: dict[str, threading.Thread] = {}
        self._started_at: dict[str, float] = {}
        self._restart_delays: dict[str, float] = {}
        self._restart_at: dict[str, float] = {}
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._monitor: threading.Thread | None = None

    # Start every service and the monitor thread that restarts the ones that exit.
    def start(self) -> None:
        for spec in self._services:
            self._spawn(spec)

        if self._services:
            self._monitor = threading.Thread(target=self._monitor_loop, name="pulsehr-service-monitor", daemon=True)
            self._monitor.start()

    # Stop the monitor, ask every service to exit and kill the ones that do not exit in time.
    def stop(self) -> None:
        self._stopping.set()
        if self._monitor is not None:
            self._monitor.join(timeout=self.POLL_INTERVAL_SECONDS * 4)

        with self._lock:
            processes = list(self._processes.items())
            relays = list(self._relays.values())

        for _, process in processes:
            if process.poll() is None:
                process.terminate()

        deadline = time.monotonic() + self.STOP_TIMEOUT_SECONDS
        for name, process in processes:
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                self._print(f"Service '{name}' did not stop in time and was killed.")
                process.kill()
                process.wait()

        # The relays end with the output of their processes; the join only lets the last lines through.
        for relay in relays:
            relay.join(timeout=1.0)

    # Print one supervisor line to the shared console.
    def _print(self, message: str) -> None:
        console.write(message, source="PULSEHR")

    # Return the environment of a service: unbuffered UTF-8 output that this process relays and prefixes.
    def _service_environment(self, spec: ServiceSpec) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env[console.LOG_SOURCE_ENV] = spec.name
        env[console.LOG_RELAYED_ENV] = "1"
        return env

    # Start one service process with its output relay; a start failure is retried like an exit.
    def _spawn(self, spec: ServiceSpec) -> None:
        try:
            process = subprocess.Popen(
                list(spec.args),
                cwd=str(self._cwd) if self._cwd else None,
                env=self._service_environment(spec),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            self._print(f"Service '{spec.name}' could not be started: {exc}")
            self._schedule_restart(spec.name, time.monotonic())
            return

        relay = threading.Thread(
            target=self._relay_output,
            args=(spec.name, process),
            name=f"pulsehr-relay-{spec.name}",
            daemon=True,
        )
        with self._lock:
            self._processes[spec.name] = process
            self._relays[spec.name] = relay
            self._started_at[spec.name] = time.monotonic()
        relay.start()

        if self._log:
            self._print(f"Service '{spec.name}' started (pid {process.pid}).")

    # Print every output line of one service with its name until the process closes its output.
    def _relay_output(self, name: str, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            text = line.rstrip("\r\n")
            if text:
                console.write(text, source=name)

    # Plan the restart of one service, doubling the delay while it keeps failing quickly.
    def _schedule_restart(self, name: str, now: float) -> float:
        ran_for = now - self._started_at.get(name, now)
        previous_delay = self._restart_delays.get(name)
        if previous_delay is None or ran_for >= self.STABLE_RUN_SECONDS:
            delay = self.RESTART_DELAY_SECONDS
        else:
            delay = min(previous_delay * 2, self.MAX_RESTART_DELAY_SECONDS)

        self._restart_delays[name] = delay
        self._restart_at[name] = now + delay
        return delay

    # Watch the services until the supervisor stops and restart the ones that exited.
    def _monitor_loop(self) -> None:
        while not self._stopping.wait(self.POLL_INTERVAL_SECONDS):
            now = time.monotonic()
            for spec in self._services:
                if self._stopping.is_set():
                    return

                with self._lock:
                    process = self._processes.get(spec.name)
                if process is not None and process.poll() is None:
                    continue

                # A freshly exited service gets a restart time; a waiting one starts once that time comes.
                if spec.name not in self._restart_at:
                    delay = self._schedule_restart(spec.name, now)
                    exit_code = process.returncode if process is not None else None
                    self._print(f"Service '{spec.name}' exited with code {exit_code}; restarting in {delay:.0f} s.")
                elif now >= self._restart_at[spec.name]:
                    del self._restart_at[spec.name]
                    self._spawn(spec)
