import io
import json
import zipfile
from fastapi import FastAPI
from fastapi.testclient import TestClient
from aiside import video_demo


def client():
    app=FastAPI();app.include_router(video_demo.router)
    return TestClient(app)


def test_prototype_package_is_honest_and_contains_only_selected_shots():
    response=client().post('/api/demo/video/export',json={'project':'演示项目','shots':[{'id':2,'description':'信件特写','camera':'缓推'}]})
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        assert set(z.namelist())=={'shot-2.mp4','keyframe-2.jpg','manifest.json','README.txt'}
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['generated_by_model'] is False
        assert manifest['status']=='prototype_unvalidated'
        assert manifest['shots'][0]['description']=='信件特写'
        assert b'ftyp' in z.read('shot-2.mp4')[:32]


def test_prototype_export_missing_media_has_visible_error(tmp_path,monkeypatch):
    monkeypatch.setattr(video_demo,'MEDIA_DIR',tmp_path)
    response=client().post('/api/demo/video/export',json={'shots':[{'id':1,'description':'镜头'}]})
    assert response.status_code==503 and '素材缺失' in response.json()['detail']


def test_prototype_export_rejects_empty_unknown_duplicate_shots():
    for shots in [[],[{'id':99,'description':'x'}],[{'id':1,'description':'x'}]*2]:
        assert client().post('/api/demo/video/export',json={'shots':shots}).status_code in {400,422}
