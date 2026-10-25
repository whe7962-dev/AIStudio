import io
import json
import subprocess
import uuid
from types import SimpleNamespace

import imageio_ffmpeg
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from aiside import video_real as real, video_workflow as wf
from aiside.providers.seedream import SeedreamProvider

@pytest.fixture
def setup(tmp_path,monkeypatch):
    app=FastAPI();app.include_router(real.router);app.include_router(wf.router)
    app.state.settings=SimpleNamespace(data_dir=tmp_path)
    monkeypatch.setattr(real,'config',lambda:('https://video.example/api/v1','unit-key','wan3.0-video-prime'))
    monkeypatch.setattr(real,'start',lambda *a,**k:None)
    return TestClient(app),tmp_path


def upload(c):
    b=io.BytesIO();Image.new('RGB',(256,256),'red').save(b,'PNG')
    return c.post('/api/demo/wan/assets',files={'image':('role.png',b.getvalue(),'image/png')}).json()['id']


def test_board_persists_arbitrary_shots_and_rejects_cycles_stale_writes(setup):
    c,root=setup
    payload={'revision':0,'story':'同一人物经历两个事件','roles':[{'id':'role1','name':'主角'}],
             'shots':[{'id':4,'description':'开场','role_ids':['role1']},{'id':9,'description':'接续','previous':4,'role_ids':['role1']}], 'positions':{'shot:4':[300,50]}}
    assert c.put('/api/demo/wan/board',json=payload).status_code==200
    assert c.put('/api/demo/wan/board',json=payload).status_code==409
    saved=c.get('/api/demo/wan/board').json()['board']
    assert saved['shots'][1]['previous']==4 and saved['positions']['shot:4']==[300,50]
    saved['shots'][0]['previous']=9
    assert c.put('/api/demo/wan/board',json=saved).status_code==400


def test_role_reference_is_actually_sent_to_wan_without_invalid_first_frame_mix(setup,monkeypatch):
    c,root=setup;aid=upload(c);rid=str(uuid.uuid4());p={'request_id':rid,'shot':4,'prompt':'同一角色走入房间','references':[{'asset_id':aid,'name':'主角'}],'workflow_signature':'same-ref','video_mode':'reference'}
    assert c.post('/api/demo/wan/jobs',json=p).status_code==200
    folder=root/'video'/rid;(folder/'keyframe.jpg').write_bytes((root/'video_assets'/aid/'image.jpg').read_bytes())
    calls=[]
    def post(url,**kw):
        calls.append(kw['json']);return httpx.Response(400,json={'code':'test-end','message':'stop'})
    monkeypatch.setattr(real.httpx,'post',post)
    real.worker(folder,'https://video.example/api/v1','unit-key','wan3.0-video-prime',True)
    media=calls[0]['input']['media']
    assert len(media)==2 and {m['type'] for m in media}=={'reference_image'}
    assert '主角' in calls[0]['input']['prompt'] and all(m['url'].startswith('data:image/jpeg;base64,') for m in media)
    manifest=json.loads((folder/'manifest.json').read_text())
    assert manifest['references'][0]['asset_id']==aid and manifest['workflow_signature']=='same-ref'


def test_missing_reference_is_rejected_before_paid_submission(setup):
    c,root=setup
    r=c.post('/api/demo/wan/jobs',json={'request_id':str(uuid.uuid4()),'shot':4,'prompt':'x','references':[{'asset_id':str(uuid.uuid4()),'name':'missing'}]})
    assert r.status_code==404 and not (root/'video').exists()


def test_seedream_receives_multiple_identity_and_continuity_refs(monkeypatch):
    p=SeedreamProvider(SimpleNamespace(demo_base_url='https://image.example',demo_api_key='unit-key',demo_model_draft='draft',demo_model_final='final',demo_model_edit='edit'))
    seen=[]
    monkeypatch.setattr('aiside.providers.seedream.httpx.post',lambda *a,**k:seen.append(k['json']) or httpx.Response(200,json={'data':[{'b64_json':'eA=='}]}))
    p.generate(prompt='同一角色',anchor_refs=['data:image/jpeg;base64,YQ==','data:image/jpeg;base64,Yg=='])
    assert seen[0]['image']==['data:image/jpeg;base64,YQ==','data:image/jpeg;base64,Yg==']


def make_clip(root,uid,color,shot):
    p=root/'video'/uid;real.save(p,{'id':uid,'status':'success','shot':shot,'duration':.5,'task_id':'remote-'+str(shot)})
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=320x240:r=30:d=0.5','-c:v','libx264','-pix_fmt','yuv420p',str(p/'video.mp4')],check=True,capture_output=True)
    return p


def test_actual_merge_preserves_order_and_outputs_one_decodable_video(setup):
    c,root=setup;ids=[str(uuid.uuid4()),str(uuid.uuid4())];paths=[make_clip(root,ids[0],'red',1),make_clip(root,ids[1],'blue',2)]
    mid=str(uuid.uuid4());folder=root/'video_merges'/mid
    real.save(folder,{'id':mid,'status':'merging','sources':[{'id':x} for x in ids],'duration':1})
    wf.compose(folder,[p/'video.mp4' for p in paths])
    assert real.read(folder)['status']=='success'
    r=c.get('/api/demo/wan/merges/'+mid+'/video');assert r.status_code==200 and b'ftyp' in r.content[:64]
    colors=[]
    for t in ['0.1','0.7']:
        out=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-ss',t,'-i',str(folder/'film.mp4'),'-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
        colors.append(out)
    assert colors[0][0]>colors[0][2] and colors[1][2]>colors[1][0]


def test_continuity_extracts_actual_last_frame(setup):
    c,root=setup;uid=str(uuid.uuid4());make_clip(root,uid,'blue',1)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(data_dir=root))))
    raw=wf.last_frame(request,uid)
    with Image.open(io.BytesIO(raw)) as image:
        red,green,blue=image.getpixel((10,10));assert blue>red and blue>green


def test_merge_rejects_incomplete_sources(setup):
    c,root=setup;ids=[str(uuid.uuid4()),str(uuid.uuid4())]
    for i,uid in enumerate(ids):real.save(root/'video'/uid,{'status':'generating','shot':i+1})
    assert c.post('/api/demo/wan/merges',json={'request_id':str(uuid.uuid4()),'ids':ids}).status_code==409


def test_first_frame_mode_carries_identity_through_frame_without_direct_refs(setup,monkeypatch):
    c,root=setup;aid=upload(c);rid=str(uuid.uuid4());raw=(root/'video_assets'/aid/'image.jpg').read_bytes()
    import base64
    p={'request_id':rid,'shot':4,'prompt':'x','references':[{'asset_id':aid,'name':'主角'}],
       'image':'data:image/jpeg;base64,'+base64.b64encode(raw).decode(),'video_mode':'first_frame'}
    assert c.post('/api/demo/wan/jobs',json=p).status_code==200
    seen=[]
    monkeypatch.setattr(real.httpx,'post',lambda *a,**k:seen.append(k['json']) or httpx.Response(403,json={'code':'AccessDenied.Unpurchased'}))
    real.worker(root/'video'/rid,'https://video.example/api/v1','unit-key','wan3.0-video-prime',True)
    assert [m['type'] for m in seen[0]['input']['media']]==['first_frame']
    assert real.read(root/'video'/rid)['reference_transport']=='via_keyframe'


def test_first_frame_mode_rejects_unused_references(setup):
    c,root=setup;aid=upload(c)
    result=c.post('/api/demo/wan/jobs',json={'request_id':str(uuid.uuid4()),'shot':1,'prompt':'同一角色','references':[{'asset_id':aid,'name':'角色'}]})
    assert result.status_code==400 and not (root/'video').exists()


def test_changes_and_frame_confirmation_persist_with_limits(setup):
    c,root=setup;frame=str(uuid.uuid4())
    board={'shots':[{'id':1,'description':'base action','changes':['slower','keep looking'],'confirmed_frame_id':frame}]}
    response=c.put('/api/demo/wan/board',json=board)
    assert response.status_code==200
    saved=c.get('/api/demo/wan/board').json()['board']
    assert saved['shots'][0]['changes']==['slower','keep looking']
    assert saved['shots'][0]['description']=='base action'
    assert saved['shots'][0]['confirmed_frame_id']==frame
    saved['shots'][0]['changes']=['x']*9
    assert c.put('/api/demo/wan/board',json=saved).status_code==422
