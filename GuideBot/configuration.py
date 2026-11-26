"""Location of the operator-editable files; internal contracts stay in backend code."""
from pathlib import Path

USER_CONFIG_DIRECTORY = Path(__file__).resolve().parents[1] / 'developer'


def read_prompt(name, directory=USER_CONFIG_DIRECTORY):
    path = Path(directory) / name
    text = path.read_text(encoding='utf-8').strip()
    if not text:
        raise ValueError('Instructions file is empty: {}'.format(path))
    return text
