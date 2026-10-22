"""Reference metadata must load from the configured container seed mount."""
import importlib.util
import json
from pathlib import Path

import pytest

from app.config import settings


@pytest.mark.parametrize(
    "module_name,filename,attribute,payload,expected",
    [
        ("query_aliases", "query_aliases.json", "ALIASES",
         {"topics": {}, "keywords": {"container-probe": "mounted alias"}},
         {"topics": {}, "keywords": {"container-probe": "mounted alias"}}),
        ("accepted_publications", "accepted_publications.json", "REFERENCE_ROWS",
         {"papers": [{"reference_id": "mounted-reference"}]},
         [{"reference_id": "mounted-reference"}]),
    ],
)
def test_reference_metadata_loads_from_configured_seed_directory(
    tmp_path, monkeypatch, module_name, filename, attribute, payload, expected
):
    (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(settings, "seeds_dir", tmp_path)
    source = Path(__file__).resolve().parents[1] / "app/services" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"seed_mount_probe_{module_name}", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert getattr(module, attribute) == expected
