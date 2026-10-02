import csv
from pathlib import Path
from app.services.tagging import score_text


def test_requested_priority_topics_have_positive_and_negative_rules():
    seeds = Path(__file__).resolve().parents[2] / 'seeds'
    with (seeds / 'direction_rules.csv').open(encoding='utf8',newline='') as f:
        rows = list(csv.DictReader(f))
    for code,title in [('ml','Federated Learning for Recommendation'),('dl','Graph Neural Networks for Retrieval'),('ai','Responsible AI Systems')]:
        rules=[(1,r['keyword'],float(r['weight']),r['field']) for r in rows if r['direction_code']==code]
        assert score_text(rules,title,None).get(1,0)>=2
        assert score_text(rules,'Editorial Board and Annual Meeting',None).get(1,0)==0
