"""Ad UI contract: real parameters, reference identity, and composition geometry."""
import base64
import io
import uuid
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from aiside import video_real as real, video_workflow as wf

@pytest.fixture
def setup(tmp_path,monkeypatch):
    app=FastAPI();app.include_router(real.router);app.include_router(wf.router)
    app.state.settings=SimpleNamespace(data_dir=tmp_path)
    app.state.provider=SimpleNamespace(name='test-provider')
    monkeypatch.setattr(real,'config',lambda:('https://unit.example/v1','unit-test-key','wan3.0-video-prime'))
    monkeypatch.setattr(real,'start',lambda *a,**k:None)
    return TestClient(app),tmp_path

def asset(c):
    b=io.BytesIO();Image.new('RGB',(480,854),'blue').save(b,'PNG')
    return c.post('/api/demo/wan/assets',files={'image':('product.png',b.getvalue(),'image/png')}).json()['id'],b.getvalue()

@pytest.mark.parametrize("seconds", [2, 7, 20, 30])
def test_ad_requested_video_parameters_reach_provider(setup,monkeypatch,seconds):
    c,root=setup;aid,raw=asset(c);uid=str(uuid.uuid4())
    body={'request_id':uid,'shot':1,'prompt':'展示包袋细节','content_type':'ad','ratio':'9:16','resolution':'1080P','duration':seconds,
          'references':[{'asset_id':aid,'name':'商品背包'}],'image':'data:image/png;base64,'+base64.b64encode(raw).decode()}
    r=c.post('/api/demo/wan/jobs',json=body);assert r.status_code==200
    seen=[]
    monkeypatch.setattr(real.httpx,'post',lambda *a,**k:seen.append(k['json']) or httpx.Response(400,json={'code':'test-stop'}))
    real.worker(root/'video'/uid,'https://unit.example/v1','unit-test-key','wan3.0-video-prime',True)
    assert {k:seen[0]['parameters'][k] for k in ['ratio','resolution','duration']}=={'ratio':'9:16','resolution':'1080P','duration':seconds}
    assert [m['type'] for m in seen[0]['input']['media']]==['first_frame']
    assert r.json()['content_type']=='ad'
    body['request_id']=str(uuid.uuid4());body['duration']=0
    assert c.post('/api/demo/wan/jobs',json=body).status_code==422

def test_ad_rejects_missing_product_before_any_job(setup):
    c,root=setup
    body={'request_id':str(uuid.uuid4()),'shot':1,'prompt':'广告','content_type':'ad'}
    assert c.post('/api/demo/wan/keyframes',json=body).status_code==400
    assert c.post('/api/demo/wan/jobs',json=body).status_code==400
    assert not (root/'video_frames').exists() and not (root/'video').exists()

def test_ad_frame_preserves_reference_and_requests_portrait_without_drama(setup):
    c,root=setup;aid,raw=asset(c);path=root/'video_frames'/str(uuid.uuid4())
    real.save(path,{'id':path.name,'status':'generating','content_type':'ad','ratio':'9:16','prompt':'背包特写','reference_names':['原始商品','相邻帧']})
    calls=[]
    class Provider:
        def generate(self,**kwargs):
            calls.append(kwargs);b=io.BytesIO();Image.new('RGB',(kwargs['width'],kwargs['height']),'blue').save(b,'PNG');return SimpleNamespace(data=b.getvalue())
    real.frame_worker(path,Provider(),[raw,raw])
    assert real.read(path)['status']=='success'
    assert (calls[0]['width'],calls[0]['height'])==(864,1536)
    assert len(calls[0]['anchor_refs'])==2
    assert '短剧' not in calls[0]['prompt'] and '商品' in calls[0]['prompt']

def test_ad_frame_wrong_ratio_is_not_silently_accepted(setup):
    c,root=setup;aid,raw=asset(c);path=root/'video_frames'/str(uuid.uuid4())
    real.save(path,{'status':'generating','content_type':'ad','ratio':'16:9','prompt':'背包'})
    class Provider:
        def generate(self,**kwargs):return SimpleNamespace(data=raw)
    real.frame_worker(path,Provider(),[raw])
    assert real.read(path)['status']=='failed'

def test_portrait_merge_uses_selected_dimensions_and_preserves_order(setup,monkeypatch):
    c,root=setup;ids=[str(uuid.uuid4()),str(uuid.uuid4())]
    for i,uid in enumerate(ids):
        p=root/'video'/uid;real.save(p,{'status':'success','id':uid,'shot':i+1,'duration':10});(p/'video.mp4').write_bytes(b'placeholder')
    monkeypatch.setattr(wf,'threading',SimpleNamespace(Thread=lambda **kwargs:SimpleNamespace(start=lambda:None)))
    response=c.post('/api/demo/wan/merges',json={'request_id':str(uuid.uuid4()),'ids':ids,'ratio':'9:16','resolution':'720P'})
    assert response.status_code==200
    d=response.json();assert (d['width'],d['height'],d['resolution'])==(720,1280,'720x1280')
    assert [s['id'] for s in d['sources']]==ids

@pytest.mark.parametrize("seconds", [0, 1, 31, 7.5, "7", True, None])
def test_invalid_duration_rejected_before_job(setup,seconds):
    c,root=setup
    body={'request_id':str(uuid.uuid4()),'shot':1,'prompt':'广告','duration':seconds}
    assert c.post('/api/demo/wan/jobs',json=body).status_code==422
    assert not (root/'video'/body['request_id']).exists()
