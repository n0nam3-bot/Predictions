from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent


def load(path=None):
    with open(path or ROOT / "config.yaml") as fh:
        return yaml.safe_load(fh)
