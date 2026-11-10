# Copyright NGGT.LightKeeper. All Rights Reserved.

from __future__ import annotations

import logging
import os
import threading
import time

# Source name printed before the lines of this process, and the flag of a process whose output the
# parent process relays and prefixes itself.
LOG_SOURCE_ENV = "PULSEHR_LOG_SOURCE"
LOG_RELAYED_ENV = "PULSEHR_LOG_RELAYED"

# Source of the lines printed by the site process.
DEFAULT_SOURCE = "Site"

_print_lock = threading.Lock()


# Return the source name of this process.
def current_source() -> str:
    return os.environ.get(LOG_SOURCE_ENV) or DEFAULT_SOURCE


# Return whether a parent process prefixes the output of this process.
def is_relayed() -> bool:
    return os.environ.get(LOG_RELAYED_ENV) == "1"


# Prefix every line of the text with the time and the source name.
def format_lines(source: str, text: str) -> str:
    stamp = time.strftime("%H:%M:%S")
    lines = str(text).splitlines() or [""]
    return "\n".join(f"{stamp} [{source}] {line}" for line in lines)


# Print the text to the shared console. A relayed process prints it as is, because the parent adds
# the prefix; otherwise the time and the source are added here.
def write(text: str, source: str | None = None) -> None:
    if is_relayed() and source is None:
        output = str(text)
    else:
        output = format_lines(source or current_source(), text)

    with _print_lock:
        print(output, flush=True)


# Format log records for the shared console: level, logger and message with the same prefix as write().
class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = f"{record.levelname} {record.name}: {record.getMessage()}"
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            text += "\n" + self.formatStack(record.stack_info)
        return text if is_relayed() else format_lines(current_source(), text)
