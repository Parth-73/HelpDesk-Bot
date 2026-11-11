"""Versioned calibration used only with proven bounded intent equivalence."""
import json
from pathlib import Path
from .query_equivalence import VERSION


def operating_point(fingerprint):
    path = Path(__file__).resolve().parents[2] / 'semantic_calibration.json'
    try:
        data = json.loads(path.read_text())
        if data['equivalence_version'] == VERSION and data['model_fingerprint'] == fingerprint:
            return data['threshold'], data['margin']
    except (OSError, ValueError, KeyError):
        pass
    return None
