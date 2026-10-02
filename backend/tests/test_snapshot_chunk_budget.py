from app.models import Paper
from app.services.snapshot import export_snapshot


def test_default_snapshot_chunks_reduce_home_manifest_without_dropping_records(
    db, session_factory, sample_venue, tmp_path
):
    db.add_all(
        [
            Paper(
                source="manual",
                title=f"Graph processing study {i}",
                title_norm=f"graph processing study {i}",
                venue_id=sample_venue.id,
                year=2024,
                ccf_level="A",
                venue_confirmed=1,
                doi=f"10.1000/paper.{i}",
                official_url=f"https://doi.org/10.1000/paper.{i}",
            )
            for i in range(1001)
        ]
    )
    db.commit()
    result = export_snapshot(session_factory, tmp_path / "snapshot")
    assert result["paper_count"] == 1001
    assert [c["count"] for c in result["chunks"]] == [1000, 1]
