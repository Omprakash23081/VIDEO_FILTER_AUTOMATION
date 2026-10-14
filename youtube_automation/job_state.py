import json
import os
import sys
import threading
import time
from contextlib import contextmanager

from . import config

_lock = threading.Lock()
_output_lock = threading.Lock()


def safe_print(*args, **kwargs):
    """Write one complete log message without concurrent output interleaving."""
    with _output_lock:
        print(*args, **kwargs)


def _load_manifest():
    try:
        with open(config.MANIFEST_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def update_part(part_number, **statuses):
    key = f"PART-{part_number}"
    with _lock:
        manifest = _load_manifest()
        manifest.setdefault(key, {}).update(statuses)
        temporary_path = f"{config.MANIFEST_PATH}.part"
        os.makedirs(os.path.dirname(config.MANIFEST_PATH) or ".", exist_ok=True)
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(manifest, file, indent=2, sort_keys=True)
        os.replace(temporary_path, config.MANIFEST_PATH)


def record_failure(stage, part_number, message):
    with _lock:
        os.makedirs(os.path.dirname(config.FAILED_JOBS_PATH) or ".", exist_ok=True)
        with open(config.FAILED_JOBS_PATH, "a", encoding="utf-8") as file:
            file.write(f"PART-{part_number} | {stage} | {message}\n")


def record_metric(
    stage,
    status,
    duration_seconds,
    part_number=None,
    attempts=1,
    error=None,
    item_count=None,
):
    event = {
        "timestamp": time.time(),
        "stage": stage,
        "status": status,
        "duration_seconds": round(duration_seconds, 3),
        "attempts": attempts,
    }
    if part_number is not None:
        event["part_number"] = str(part_number)
    if error:
        event["error"] = str(error)
    if item_count is not None:
        event["item_count"] = item_count
        if duration_seconds > 0:
            event["items_per_minute"] = round(item_count * 60 / duration_seconds, 3)
    with _lock:
        os.makedirs(os.path.dirname(config.METRICS_PATH) or ".", exist_ok=True)
        with open(config.METRICS_PATH, "a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=True) + "\n")


@contextmanager
def pipeline_lock():
    os.makedirs(os.path.dirname(config.LOCK_PATH) or ".", exist_ok=True)

    if sys.platform == "win32":
        import msvcrt

        lock_file = open(config.LOCK_PATH, "a+b")
        locked = False
        try:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError(
                    f"Another pipeline process is already running: {config.LOCK_PATH}"
                ) from error
            locked = True
            lock_file.seek(0)
            lock_file.write(str(os.getpid()).encode("ascii"))
            lock_file.truncate()
            lock_file.flush()
            yield
        finally:
            if locked:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            lock_file.close()
        return

    try:
        descriptor = os.open(config.LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        try:
            with open(config.LOCK_PATH, "r", encoding="ascii") as file:
                process_id = int(file.read().strip())
            os.kill(process_id, 0)
        except PermissionError as error:
            raise RuntimeError(f"Another pipeline process is already running: {config.LOCK_PATH}") from error
        except (FileNotFoundError, ValueError, ProcessLookupError, OSError):
            try:
                os.remove(config.LOCK_PATH)
            except FileNotFoundError:
                pass
            descriptor = os.open(config.LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        else:
            raise RuntimeError(f"Another pipeline process is already running: {config.LOCK_PATH}") from error

    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as file:
            file.write(str(os.getpid()))
        yield
    finally:
        try:
            os.remove(config.LOCK_PATH)
        except FileNotFoundError:
            pass
