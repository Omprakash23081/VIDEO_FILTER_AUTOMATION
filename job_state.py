import json
import os
import threading

import config

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
