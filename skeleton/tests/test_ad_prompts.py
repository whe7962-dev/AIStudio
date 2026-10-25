from fastapi import FastAPI
from fastapi.testclient import TestClient
from aiside.ad_prompts import router


def client():
    app=FastAPI();app.include_router(router);return TestClient(app)


def test_minimal_brief_keeps_unknown_facts_pending_and_never_generates():
    c=client();r=c.post('/api/demo/ad/prepare',json={'product':'背包','requirement':'清晨通勤广告'})
    assert r.status_code==200
    d=r.json();assert d['status']=='draft' and d['requires_confirmation'] and not d['model_called']
    assert '清晨通勤广告' in d['shared_context']
    assert any('卖点尚未提供' in x for x in d['pending_checks'])
    assert '未提供，不得自行补充' in d['shared_context']
    assert len(d['scenes'])==3 and len({s['purpose'] for s in d['scenes']})==3
    assert '同一商品参考' in d['shared_context']
    assert 'job_id' not in d and 'task_id' not in d


def test_all_templates_retain_user_facts_without_replacing_the_brief():
    c=client();catalog=c.get('/api/demo/ad/catalog').json()
    assert len(catalog['templates'])==4
    assert {'product_identity','facts_only','review_first'}<={r['id'] for r in catalog['rules']}
    for template in catalog['templates']:
        body={'product':'旅行杯','requirement':'不出现人物','facts':'容量350ml，磨砂白色','template':template['id']}
        d=c.post('/api/demo/ad/prepare',json=body).json()
        assert d['brief']['requirement']==body['requirement']
        assert body['facts'] in d['prompt']
        assert all(s['duration']==5 for s in d['scenes'])
        assert '不擅自增加代言人' in d['prompt']


def test_missing_whitespace_oversized_and_unknown_inputs_rejected():
    c=client()
    for body in [{}, {'product':' ','requirement':'广告'}, {'product':'杯子','requirement':' '},
                 {'product':'杯子','requirement':'广告','template':'unknown'},
                 {'product':'杯子','requirement':'x'*1801}]:
        assert c.post('/api/demo/ad/prepare',json=body).status_code==422
