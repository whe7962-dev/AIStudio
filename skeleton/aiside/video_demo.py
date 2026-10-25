"""Local prototype export only: never calls a video model."""
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from .settings import ROOT_DIR

router = APIRouter()
MEDIA_DIR = ROOT_DIR / 'web' / 'assets' / 'prototype'

class Shot(BaseModel):
    id: Literal[1, 2, 3]
    description: str = Field(max_length=500)
    camera: str = Field(default='固定', max_length=40)

class PrototypeExport(BaseModel):
    project: str = Field(default='我的创作项目', max_length=60)
    shots: list[Shot] = Field(min_length=1, max_length=3)
    reference_asset: str = Field(default='', max_length=300)

@router.post('/api/demo/video/export')
def export_prototype(body: PrototypeExport):
    ids = [s.id for s in body.shots]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail='镜头不能重复')
    manifest = {
        'project': body.project, 'status': 'prototype_unvalidated',
        'generated_by_model': False, 'exported_at': datetime.now(timezone.utc).isoformat(),
        'notice': '原型 / 验证中。视频为预置本地示例，不随分镜或参考素材生成。',
        'reference_asset': body.reference_asset,
        'reference_note': '仅记录素材标识，不包含参考素材文件；不代表该素材参与视频生成。',
        'shots': [{**s.model_dump(), 'duration_seconds': 4,
                   'video': f'shot-{s.id}.mp4', 'keyframe': f'keyframe-{s.id}.jpg'} for s in body.shots],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for shot in body.shots:
            for name in [f'shot-{shot.id}.mp4', f'keyframe-{shot.id}.jpg']:
                path = MEDIA_DIR / name
                if not path.is_file():
                    raise HTTPException(status_code=503, detail='本地示例素材缺失，请恢复素材后重试')
                archive.write(path, arcname=name)
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr('README.txt', '原型 / 验证中\n仅供流程演示，所有视频均为本地预置示例，未接入视频生成模型。\n分镜描述与参考素材不改变示例内容。\n每镜头4秒，960×540，24fps，H.264，无音轨。\n')
    return Response(buffer.getvalue(), media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="video-prototype.zip"'})
