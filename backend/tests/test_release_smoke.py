"""Keep empty-installation smoke checks aligned with the configured seed identities."""
import csv
import importlib.util
import json

import pytest

from app.config import PROJECT_ROOT


@pytest.fixture
def smoke():
    spec = importlib.util.spec_from_file_location(
        "release_smoke_under_test", PROJECT_ROOT / "scripts" / "smoke_release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_seed_tree(smoke, monkeypatch, tmp_path, direction_count):
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    with (seeds / "venues.csv").open("w", encoding="utf-8-sig", newline="") as source:
        writer = csv.DictWriter(source, fieldnames=["abbr"])
        writer.writeheader()
        writer.writerows([{"abbr": "ICML"}, {"abbr": "PODS"}])
    codes = [f"topic-{i}" for i in range(direction_count)]
    with (seeds / "directions.csv").open("w", encoding="utf-8-sig", newline="") as source:
        writer = csv.DictWriter(source, fieldnames=["code", "enabled"])
        writer.writeheader()
        writer.writerows({"code": code, "enabled": 1} for code in codes)
        writer.writerow({"code": "retired", "enabled": 0})
    monkeypatch.setattr(smoke, "__file__", str(tmp_path / "scripts" / "smoke_release.py"))
    return codes


def install_responses(smoke, monkeypatch, codes):
    replies = {
        "/": (200, {"X-Content-Type-Options": "nosniff"}, b"LitHub Pavilion"),
        "/api/health": {"db": "ok"},
        "/api/stats/dashboard": {
            "total": 0, "configured_venues": 2,
            "directions": [{"code": code} for code in codes],
        },
        "/api/crawl/status": {"mode": "links"},
        "/api/papers/1/pdf": (404, {}, b""),
        "/api/search?q=speculative": {"total": 0},
        "/api/venues": {"items": [{"abbr": "ICML"}, {"abbr": "PODS"}]},
        "/api/papers?level=C": (
            400, {}, json.dumps({"error": {"code": "INVALID_PARAM"}}).encode(),
        ),
    }

    def get(path):
        result = replies[path]
        return result if isinstance(result, tuple) else (200, {}, json.dumps(result).encode())

    monkeypatch.setattr(smoke, "get", get)


@pytest.mark.parametrize("direction_count", [2, 16])
def test_smoke_uses_enabled_seed_identities_not_a_fixed_topic_count(
    smoke, monkeypatch, tmp_path, capsys, direction_count
):
    codes = configure_seed_tree(smoke, monkeypatch, tmp_path, direction_count)
    install_responses(smoke, monkeypatch, list(reversed(codes)))
    smoke.main()
    assert f"{direction_count} research directions" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["missing", "extra", "wrong_identity", "duplicate"])
def test_smoke_rejects_incorrect_direction_identities(smoke, monkeypatch, tmp_path, change):
    codes = configure_seed_tree(smoke, monkeypatch, tmp_path, 2)
    actual = {
        "missing": codes[:1],
        "extra": [*codes, "unconfigured"],
        "wrong_identity": [codes[0], "unconfigured"],
        "duplicate": [*codes, codes[0]],
    }[change]
    install_responses(smoke, monkeypatch, actual)
    with pytest.raises(AssertionError):
        smoke.main()


def test_smoke_does_not_accept_a_stale_nine_direction_installation(smoke, monkeypatch, tmp_path):
    codes = configure_seed_tree(smoke, monkeypatch, tmp_path, 16)
    install_responses(smoke, monkeypatch, codes[:9])
    with pytest.raises(AssertionError):
        smoke.main()
