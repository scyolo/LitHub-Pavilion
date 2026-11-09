"""Exercise the production search verification script on the current format."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.models import PaperDirection
from app.services.snapshot import export_snapshot


def test_search_release_script_accepts_current_detached_direct_lookup(
    db, session_factory, sample_paper, sample_direction, tmp_path
):
    node=shutil.which('node')
    if node is None:
        pytest.skip('Node is required for the cross-language release script')
    db.add(PaperDirection(paper_id=sample_paper.id,direction_id=sample_direction.id))
    db.commit()
    manifest=export_snapshot(session_factory,tmp_path/'snapshot')
    root=Path(__file__).resolve().parents[2]
    env={**os.environ,'SNAPSHOT_DIR':str(tmp_path/'snapshot'),'SEARCH_SAMPLE_LIMIT':'1'}
    result=subprocess.run([node,str(root/'frontend/scripts/check-snapshot-search.js'),str(tmp_path/'report.json')],
                          cwd=root/'frontend',env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    report=json.loads((tmp_path/'report.json').read_text('utf-8'))
    assert report['revision']==manifest['revision']
    assert report['offline_title_identity_checks']==1
