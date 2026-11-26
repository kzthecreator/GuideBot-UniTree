"""Read the private planner file written by LocalRuntime (JSON-encoded values)."""
import json
import os


def load_planner_config(path):
    allowed = {'DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL', 'DEEPSEEK_MODEL'}
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        key, separator, encoded = line.partition('=')
        if not separator or key not in allowed:
            raise ValueError('Invalid private planner configuration')
        value = json.loads(encoded)
        if not isinstance(value, str):
            raise ValueError('Invalid private planner configuration value')
        values[key] = value
    for key, value in values.items():
        os.environ.setdefault(key, value)
