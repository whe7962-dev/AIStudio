import json
import uuid
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from aiside import video_real as v

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(v,'config',lambda:('https://video.example/api/v1','unit-test-key','wan3.0-video-prime'))
    app=FastAPI();app.include_router(v.router);app.state.settings=SimpleNamespace(data_dir=tmp_path)
    calls=[];monkeypatch.setattr(v,'start',lambda *a,**k:calls.append((a,k)))
    return TestClient(app),tmp_path,calls

def body():return {'request_id':str(uuid.uuid4()),'shot':2,'prompt':'信封特写'}

def test_duplicate_submission_never_recreates_task(setup):
    c,root,calls=setup;p=body();a=c.post('/api/demo/wan/jobs',json=p);b=c.post('/api/demo/wan/jobs',json=p)
    assert a.status_code==b.status_code==200 and len(calls)==1
    assert a.json()['id']==b.json()['id'] and 'endpoint' not in a.json()
    assert 'unit-test-key' not in (root/'video'/p['request_id']/'manifest.json').read_text()

def test_validation_and_unready_export(setup,monkeypatch):
    c,root,calls=setup
    assert c.post('/api/demo/wan/jobs',json={**body(),'image':'http://localhost/private'}).status_code==400
    p=body();c.post('/api/demo/wan/jobs',json=p)
    assert c.get('/api/demo/wan/jobs/'+p['request_id']+'/video').status_code==409
    assert c.get('/api/demo/wan/jobs/not-an-id').status_code==404
    monkeypatch.setattr(v,'config',lambda:('','','wan3.0-video-prime'))
    assert c.post('/api/demo/wan/jobs',json=body()).status_code==503

def test_worker_persists_id_before_poll_and_exports(setup,monkeypatch):
    c,root,calls=setup;p=body();c.post('/api/demo/wan/jobs',json=p);path=root/'video'/p['request_id']
    def post(url,**kw):
        assert kw['json']['model']=='wan3.0-video-prime' and kw['headers']['X-DashScope-Async']=='enable'
        return httpx.Response(200,json={'output':{'task_id':'remote-123','task_status':'PENDING'}})
    def get(url,**kw):
        assert json.loads((path/'manifest.json').read_text())['task_id']=='remote-123'
        return httpx.Response(200,json={'output':{'task_status':'SUCCEEDED','video_url':'https://cdn.example/out.mp4'},'usage':{'output_video_duration':5}})
    monkeypatch.setattr(v.httpx,'post',post);monkeypatch.setattr(v.httpx,'get',get)
    monkeypatch.setattr(v,'download_video',lambda url,target:target.write_bytes(b'0000ftyp'+b'0'*100))
    v.worker(path,'https://video.example/api/v1','unit-test-key','wan3.0-video-prime',True)
    d=c.get('/api/demo/wan/jobs/'+p['request_id']).json()
    assert d['status']=='success' and d['generated_by_model'] is True
    assert c.get('/api/demo/wan/jobs/'+p['request_id']+'/video').status_code==200
    assert c.post('/api/demo/wan/export',json={'ids':[p['request_id']]}).status_code==200

def test_timeout_is_uncertain_not_auto_retried(setup,monkeypatch):
    c,root,calls=setup;p=body();c.post('/api/demo/wan/jobs',json=p);path=root/'video'/p['request_id'];requests=[]
    def timeout(*a,**kw):requests.append(1);raise httpx.ReadTimeout('timeout')
    monkeypatch.setattr(v.httpx,'post',timeout)
    v.worker(path,'https://video.example/api/v1','unit-test-key','wan3.0-video-prime',True)
    d=json.loads((path/'manifest.json').read_text())
    assert d['status']=='submission_unknown' and not d['generated_by_model'] and len(requests)==1
    assert c.post('/api/demo/wan/jobs/'+p['request_id']+'/resume').status_code==409

def test_error_never_exposes_key(setup,monkeypatch):
    c,root,calls=setup;p=body();c.post('/api/demo/wan/jobs',json=p);path=root/'video'/p['request_id']
    monkeypatch.setattr(v.httpx,'post',lambda *a,**k:httpx.Response(401,json={'code':'InvalidApiKey','message':'bad unit-test-key'}))
    v.worker(path,'https://video.example/api/v1','unit-test-key','wan3.0-video-prime',True)
    d=c.get('/api/demo/wan/jobs/'+p['request_id']).json()
    assert d['status']=='failed' and 'unit-test-key' not in json.dumps(d)

def test_download_failure_resumes_without_new_generation(setup,monkeypatch):
    c,root,calls=setup;p=body();c.post('/api/demo/wan/jobs',json=p);path=root/'video'/p['request_id']
    d=v.read(path);d.update(task_id='persisted-task',status='generating');v.save(path,d)
    submitted=[]
    monkeypatch.setattr(v.httpx,'post',lambda *a,**k:submitted.append(1))
    monkeypatch.setattr(v.httpx,'get',lambda *a,**k:httpx.Response(200,json={'output':{'task_status':'SUCCEEDED','video_url':'https://cdn.example/out.mp4'}}))
    def fail_download(*a):raise httpx.ReadTimeout('download failed')
    monkeypatch.setattr(v,'download_video',fail_download)
    v.worker(path,'https://video.example/api/v1','unit-test-key','wan3.0-video-prime',False)
    assert v.read(path)['status']=='download_failed'
    monkeypatch.setattr(v,'download_video',lambda url,target:target.write_bytes(b'0000ftyp'+b'0'*100))
    v.worker(path,'https://video.example/api/v1','unit-test-key','wan3.0-video-prime',False)
    assert v.read(path)['status']=='success' and submitted==[]

def test_server_history_can_restore_in_another_browser(setup):
    c,root,calls=setup;p=body();c.post('/api/demo/wan/jobs',json=p)
    jobs=c.get('/api/demo/wan/jobs').json()['jobs']
    assert len(jobs)==1 and jobs[0]['id']==p['request_id']
    assert 'endpoint' not in jobs[0] and 'unit-test-key' not in json.dumps(jobs)
    assert c.get('/api/demo/wan/keyframes').json()=={'frames':[]}
