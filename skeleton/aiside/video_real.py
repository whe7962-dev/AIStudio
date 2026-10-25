"""Wan 3 real generation. Credentials stay server-side; submitted tasks persist."""
import base64
import io
import json
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field
from .settings import get_settings

router = APIRouter()
_LOCK = threading.RLock()
_RUNNING = set()


class CharacterReference(BaseModel):
    asset_id: uuid.UUID
    name: str = Field(default='角色', max_length=120)


class VideoInput(BaseModel):
    request_id: uuid.UUID
    project: str = Field(default='我的创作项目', max_length=60)
    shot: int = Field(ge=1, le=999999)
    prompt: str = Field(min_length=1, max_length=10000)
    image: str = Field(default='', max_length=14_000_000)
    references: list[CharacterReference] = Field(default_factory=list, max_length=4)
    previous_video_id: uuid.UUID | None = None
    previous_frame_id: uuid.UUID | None = None
    workflow_signature: str = Field(default='', max_length=80)
    story_context: str = Field(default='', max_length=4000)
    video_mode: Literal['first_frame','reference'] = 'first_frame'
    content_type: Literal['story', 'ad'] = 'story'
    ratio: Literal['16:9', '9:16', '1:1'] = '16:9'
    resolution: Literal['480P', '720P', '1080P'] = '480P'
    duration: int = Field(default=5, strict=True, ge=2, le=30)


def config():
    get_settings()  # Loads server-side dotenv without overriding process environment.
    base = os.environ.get('VIDEO_BASE_URL', '').rstrip('/')
    key = os.environ.get('DASHSCOPE_API_KEY', '')
    model = os.environ.get('VIDEO_MODEL', 'wan3.0-video-prime')
    return base, key, model


def folder(request, job_id):
    try:
        ident = str(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(404, '视频任务不存在')
    return Path(request.app.state.settings.data_dir) / 'video' / ident


def save(path, data):
    path.mkdir(parents=True, exist_ok=True)
    tmp = path / 'manifest.tmp'
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path / 'manifest.json')


def read(path):
    try:
        return json.loads((path / 'manifest.json').read_text())
    except (OSError, ValueError):
        raise HTTPException(404, '视频任务不存在或记录损坏')


def public(data):
    return {k: v for k, v in data.items() if k not in {'endpoint'}}


def error_text(data, key):
    code = str(data.get('code', 'ServiceError'))[:80]
    message = str(data.get('message', '视频服务返回错误'))
    if key:
        message = message.replace(key, '[redacted]')
    message = re.sub(r'sk-[\w.\-]+', '[redacted]', message)
    return f'{code}: {message[:250]}'


def download_video(url, target):
    if urlparse(url).scheme != 'https':
        raise ValueError('视频下载地址无效')
    temp = target.with_suffix('.part')
    try:
        total = 0
        with httpx.stream('GET', url, timeout=120, follow_redirects=True) as response:
            response.raise_for_status()
            with temp.open('wb') as output:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > 200 * 1024 * 1024:
                        raise ValueError('视频超过200MB下载限制')
                    output.write(chunk)
        with temp.open('rb') as stream:
            header = stream.read(64)
        if total < 64 or b'ftyp' not in header:
            raise ValueError('服务返回的文件不是有效MP4')
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def worker(path, base, key, model, submit):
    token = str(path)
    try:
        data = read(path)
        if submit:
            payload = {'model': model, 'input': {'prompt': data['prompt']},
                       'parameters': {'resolution': data.get('resolution', '480P'), 'ratio': data.get('ratio', '16:9'), 'duration': data.get('duration', 5),
                                      'audio': False, 'prompt_extend': False, 'watermark': True}}
            frame = path / 'keyframe.jpg'
            refs = sorted(path.glob('reference-*.jpg'))
            if refs and data.get('generation_mode')=='reference':
                media=[{'type':'reference_image','url':'data:image/jpeg;base64,'+base64.b64encode(p.read_bytes()).decode()} for p in refs]
                notes=[f'图{i+1}是{name}。' for i,name in enumerate(data.get('reference_names',[]))]
                if frame.exists():
                    media.append({'type':'reference_image','url':'data:image/jpeg;base64,'+base64.b64encode(frame.read_bytes()).decode()})
                    notes.append(f'图{len(media)}为当前镜头构图参考。')
                payload['input']['media']=media
                identity = '严格保持同一商品的颜色、结构、包装和标识，人物出镜时保持人物一致。' if data.get('content_type') == 'ad' else '严格沿用同一角色的脸型、发型、年龄、服装和配饰，保持空间与动作衔接。'
                payload['input']['prompt']=''.join(notes)+identity+data['prompt']
            elif frame.exists():
                payload['input']['media'] = [{'type': 'first_frame', 'url': 'data:image/jpeg;base64,' + base64.b64encode(frame.read_bytes()).decode()}]
            try:
                response = httpx.post(base + '/services/aigc/video-generation/video-synthesis',
                    headers={'Authorization': 'Bearer ' + key, 'X-DashScope-Async': 'enable'}, json=payload, timeout=60)
                reply = response.json()
            except (httpx.HTTPError, ValueError):
                data.update(status='submission_unknown', error='提交结果未确认，为避免重复计费未自动重发。请核对平台任务记录。')
                save(path, data)
                return
            data['request_id'] = reply.get('request_id')
            data['task_id'] = reply.get('output', {}).get('task_id')
            if not data['task_id']:
                data.update(status='failed', error=error_text(reply, key))
                save(path, data)
                return
            data.update(status='generating', provider_status=reply.get('output', {}).get('task_status', 'PENDING'))
            save(path, data)  # Persist remote id before any polling / download.
        for _ in range(120):
            try:
                response = httpx.get(base + '/tasks/' + data['task_id'], headers={'Authorization': 'Bearer ' + key}, timeout=30)
                reply = response.json()
                if response.status_code >= 400:
                    data.update(status='query_error', error=error_text(reply, key));save(path, data);return
                result = reply.get('output', {})
                state = result.get('task_status', 'UNKNOWN')
                data.update(provider_status=state, updated_at=time.time())
                if state == 'SUCCEEDED':
                    data.update(status='downloading');save(path, data)
                    try:
                        download_video(result['video_url'], path / 'video.mp4')
                    except (httpx.HTTPError, ValueError, KeyError, OSError):
                        data.update(status='download_failed', error='视频已生成，但下载失败。点击重新查询可下载原任务，不会重新生成。');save(path, data);return
                    data.update(status='success', generated_by_model=True, usage=reply.get('usage', {}),
                                completed_at=time.time(), error=None)
                    save(path, data);return
                if state in {'FAILED', 'CANCELED', 'UNKNOWN'}:
                    data.update(status='failed', error=error_text(result, key));save(path, data);return
                data.update(status='generating', error=None);save(path, data)
            except (httpx.HTTPError, ValueError):
                data.update(error='查询暂时失败，正在继续查询原任务。');save(path, data)
            time.sleep(15)
        data.update(status='query_error', error='等待时间较长，点击重新查询原任务；不会重复生成。');save(path, data)
    finally:
        with _LOCK:
            _RUNNING.discard(token)


def start(path, base, key, model, submit=False):
    with _LOCK:
        if str(path) in _RUNNING:
            return
        _RUNNING.add(str(path))
    threading.Thread(target=worker, args=(path, base, key, model, submit), daemon=True).start()


@router.get('/api/demo/wan/config')
def get_config(request: Request):
    base, key, model = config()
    return {'configured': bool(base and key), 'model': model, 'resolution': '480P', 'duration': 5,
            'keyframes_configured': getattr(getattr(request.app.state, 'provider', None), 'name', 'stub') != 'stub',
            'ratios': ['16:9', '9:16', '1:1'], 'resolutions': ['480P', '720P', '1080P'], 'durations': list(range(2, 31)), 'duration_min': 2, 'duration_max': 30}


@router.post('/api/demo/wan/jobs')
def create_video(body: VideoInput, request: Request):
    base, key, model = config()
    if not base or not key:
        raise HTTPException(503, '真实视频服务未配置，请配置 VIDEO_BASE_URL 与 DASHSCOPE_API_KEY')
    if urlparse(base).scheme != 'https' or urlparse(base).username:
        raise HTTPException(503, '视频服务地址必须是有效HTTPS地址')
    if not body.prompt.strip():
        raise HTTPException(400, '请填写镜头描述')
    frame = None
    if body.image:
        try:
            if not body.image.startswith('data:image/'):
                raise ValueError()
            raw = base64.b64decode(body.image.split(',', 1)[1], validate=True)
            if len(raw) > 10 * 1024 * 1024:
                raise ValueError()
            with Image.open(io.BytesIO(raw)) as im:
                if min(im.size) < 240 or max(im.size) > 8000 or max(im.size) / min(im.size) > 8:
                    raise ValueError()
                output = io.BytesIO();im.convert('RGB').save(output, 'JPEG', quality=95);frame=output.getvalue()
        except Exception:
            raise HTTPException(400, '首帧必须是有效图片，单边240–8000像素，比例不超过8:1，文件不超过10MB')
    from .video_workflow import references
    refs,ref_names=references(body,request)
    if body.content_type == 'ad' and not body.references:
        raise HTTPException(400, '商品广告需要固定商品参考图')
    if refs and body.video_mode=='first_frame' and frame is None:
        raise HTTPException(400, '首帧模式需要关键帧，角色参考应先用于生成该关键帧')
    path = folder(request, str(body.request_id))
    with _LOCK:
        if (path / 'manifest.json').exists():
            return public(read(path))  # Same request ID never creates another paid task.
        data = {'id': str(body.request_id), 'project': body.project, 'shot': body.shot,
                'prompt': body.prompt, 'model': model, 'endpoint': base, 'status': 'submitting',
                'generated_by_model': False, 'created_at': time.time(), 'duration': body.duration, 'resolution': body.resolution,
                'ratio': body.ratio, 'content_type': body.content_type,
                'has_keyframe': frame is not None, 'workflow_signature':body.workflow_signature,
                'references':[r.model_dump(mode='json') for r in body.references], 'reference_names':ref_names,
                'previous_video_id':str(body.previous_video_id) if body.previous_video_id else None,
                'previous_frame_id':str(body.previous_frame_id) if body.previous_frame_id else None,
                'story_context':body.story_context,'generation_mode':body.video_mode,
                'reference_transport':'direct_to_video_model' if body.video_mode=='reference' else 'via_keyframe'}
        save(path, data)
        for i,raw in enumerate(refs):(path/f'reference-{i}.jpg').write_bytes(raw)
        if frame:
            (path / 'keyframe.jpg').write_bytes(frame)
        start(path, base, key, model, submit=True)
    return public(data)


@router.get('/api/demo/wan/jobs')
def list_videos(request: Request):
    root = Path(request.app.state.settings.data_dir) / 'video'
    jobs=[]
    for path in sorted(root.glob('*/manifest.json'), key=lambda p:p.stat().st_mtime, reverse=True)[:50]:
        try: jobs.append(public(read(path.parent)))
        except HTTPException: continue
    return {'jobs': jobs}


@router.get('/api/demo/wan/jobs/{job_id}')
def get_video(job_id: str, request: Request):
    path = folder(request, job_id)
    data = read(path)
    if data['status'] in {'submitting', 'generating', 'downloading'} and str(path) not in _RUNNING:
        base, key, model = config()
        if data.get('task_id') and base == data['endpoint'] and key:
            start(path, base, key, data['model'])
        elif not data.get('task_id'):
            data.update(status='submission_unknown', error='服务中断时提交结果未确认，请先核对平台记录，未自动重新生成。');save(path, data)
    return public(data)


@router.post('/api/demo/wan/jobs/{job_id}/resume')
def resume_video(job_id: str, request: Request):
    path=folder(request, job_id);data=read(path);base,key,model=config()
    if not data.get('task_id'):
        raise HTTPException(409, '没有可查询的远端任务ID，请核对平台记录')
    if not key or base != data['endpoint']:
        raise HTTPException(409, '当前服务配置与该任务不匹配')
    if data['status'] == 'success':
        return public(data)
    with _LOCK:
        if str(path) not in _RUNNING:
            data.update(status='generating', error=None);save(path, data)
            start(path, base, key, data['model'])
    return public(data)


@router.get('/api/demo/wan/jobs/{job_id}/video')
def video_file(job_id: str, request: Request):
    path=folder(request, job_id);data=read(path)
    if data['status'] != 'success' or not (path/'video.mp4').exists():
        raise HTTPException(409, '真实视频尚未就绪')
    return FileResponse(path/'video.mp4', media_type='video/mp4', filename=f'wan-shot-{data["shot"]}.mp4')


@router.get('/api/demo/wan/jobs/{job_id}/export')
def video_export(job_id: str, request: Request):
    path=folder(request, job_id);data=read(path)
    if data['status'] != 'success' or not (path/'video.mp4').exists():
        raise HTTPException(409, '真实视频尚未就绪')
    output=io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(path/'video.mp4', 'video.mp4')
        if (path/'keyframe.jpg').exists():z.write(path/'keyframe.jpg', 'keyframe.jpg')
        z.writestr('manifest.json', json.dumps(public(data),ensure_ascii=False,indent=2))
    return Response(output.getvalue(), media_type='application/zip', headers={'Content-Disposition':'attachment; filename="wan-real-video.zip"'})


def frame_path(request, frame_id):
    video_path = folder(request, frame_id)
    return video_path.parent.parent / 'video_frames' / video_path.name


def frame_worker(path, provider, reference):
    data = read(path)
    try:
        ad = data.get('content_type') == 'ad'
        width, height = {'16:9': (1536, 864), '9:16': (864, 1536), '1:1': (1024, 1024)}[data.get('ratio', '1:1')] if ad else (1024, 1024)
        identity = '始终保持同一商品的形状、颜色、结构、包装和标识，不添加未经确认的功能、文字或人物。' if ad else '同一角色在新镜头中保持脸型、发型、服装一致。'
        prompt = ('商品商业广告关键帧，单帧静态构图，无额外字幕，无拼贴。' if ad else '电影写实风格，短剧分镜关键帧，单帧静态构图，无字幕，无拼贴。') + data['prompt']
        if isinstance(reference,list) and reference:
            refs=['data:image/jpeg;base64,'+base64.b64encode(raw).decode() for raw in reference]
            notes=''.join(f'图{i+1}是{name}。' for i,name in enumerate(data.get('reference_names',[])))
            generated=provider.generate(prompt=notes+identity+prompt,anchor_refs=refs,width=width,height=height)
        elif reference:
            generated = provider.inpaint(image_data=reference, mask_data=None, prompt=prompt, size=f'{width}x{height}')
        else:
            generated = provider.generate(prompt=prompt, width=width, height=height)
        with Image.open(io.BytesIO(generated.data)) as img:
            if ad and abs(img.width / img.height - width / height) > .03:
                raise ValueError('关键帧比例与请求不符')
            img.convert('RGB').save(path/'keyframe.jpg', 'JPEG', quality=95)
            data['width'], data['height'] = img.size
        data.update(status='success', completed_at=time.time())
    except Exception:
        data.update(status='failed', error='关键帧生成失败，请检查图片服务配置或稍后重试。')
    save(path, data)
    with _LOCK:
        _RUNNING.discard(str(path))


@router.post('/api/demo/wan/keyframes')
def create_frame(body: VideoInput, request: Request):
    provider=request.app.state.provider
    if getattr(provider, 'name', 'stub') == 'stub':
        raise HTTPException(503, '未配置真实关键帧图片服务')
    reference=None
    if body.image:
        try:
            if not body.image.startswith('data:image/'):
                raise ValueError()
            reference=base64.b64decode(body.image.split(',',1)[1],validate=True)
            if len(reference)>10*1024*1024:raise ValueError()
            with Image.open(io.BytesIO(reference)) as img:img.verify()
        except Exception:
            raise HTTPException(400,'参考图片无效或超过10MB')
    from .video_workflow import references
    refs,ref_names=references(body,request)
    if body.content_type == 'ad' and not body.references:
        raise HTTPException(400, '商品广告需要固定商品参考图')
    if reference:refs.append(reference);ref_names.append('补充画面参考')
    path=frame_path(request,str(body.request_id))
    with _LOCK:
        if (path/'manifest.json').exists():return read(path)
        data={'id':str(body.request_id),'status':'generating','prompt':body.prompt,'shot':body.shot,
              'created_at':time.time(),'source':provider.name,'project':body.project,
              'content_type':body.content_type,'ratio':body.ratio,
              'workflow_signature':body.workflow_signature,'references':[r.model_dump(mode='json') for r in body.references],
              'previous_video_id':str(body.previous_video_id) if body.previous_video_id else None,
              'previous_frame_id':str(body.previous_frame_id) if body.previous_frame_id else None,
              'reference_names':ref_names,'story_context':body.story_context}
        save(path,data);_RUNNING.add(str(path))
        threading.Thread(target=frame_worker,args=(path,provider,refs or None),daemon=True).start()
    return data


@router.get('/api/demo/wan/keyframes')
def list_frames(request: Request):
    root=Path(request.app.state.settings.data_dir)/'video_frames'
    frames=[]
    for path in sorted(root.glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:50]:
        try: frames.append(read(path.parent))
        except HTTPException: continue
    return {'frames':frames}


@router.get('/api/demo/wan/keyframes/{frame_id}')
def get_frame(frame_id: str,request: Request):
    path=frame_path(request,frame_id);data=read(path)
    if data['status']=='generating' and str(path) not in _RUNNING:
        data.update(status='failed',error='关键帧任务被中断，请手动重试。');save(path,data)
    return data


@router.get('/api/demo/wan/keyframes/{frame_id}/image')
def frame_image(frame_id: str,request: Request):
    path=frame_path(request,frame_id)
    if read(path)['status']!='success' or not (path/'keyframe.jpg').exists():
        raise HTTPException(409,'关键帧尚未就绪')
    return FileResponse(path/'keyframe.jpg',media_type='image/jpeg')


class ExportVideos(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1,max_length=20)


@router.post('/api/demo/wan/export')
def export_videos(body: ExportVideos, request: Request):
    output=io.BytesIO();manifests=[]
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for ident in dict.fromkeys(str(i) for i in body.ids):
            path=folder(request,ident);data=read(path)
            if data['status']!='success' or not (path/'video.mp4').exists():
                raise HTTPException(409,'所选任务包含未完成视频')
            manifests.append(public(data));z.write(path/'video.mp4',ident+'/video.mp4')
            if (path/'keyframe.jpg').exists():z.write(path/'keyframe.jpg',ident+'/keyframe.jpg')
        z.writestr('manifest.json',json.dumps({'generated_by_model':True,'clips':manifests},ensure_ascii=False,indent=2))
    return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="wan-real-videos.zip"'})
