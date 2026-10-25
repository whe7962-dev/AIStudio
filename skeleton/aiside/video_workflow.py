"""Shared character references, persisted node board and local video composition."""
import io
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal

import imageio_ffmpeg
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field
from . import video_real as real

router = APIRouter()
_LOCK = threading.RLock()
_MERGING = set()


def root(request):
    return Path(request.app.state.settings.data_dir)


def ident(value):
    try:return str(uuid.UUID(str(value)))
    except ValueError:raise HTTPException(404,'资源不存在')


def jpeg(raw):
    try:
        if len(raw)>10*1024*1024:raise ValueError()
        with Image.open(io.BytesIO(raw)) as im:
            if min(im.size)<240 or max(im.size)>8000:raise ValueError()
            im.thumbnail((2048,2048));b=io.BytesIO();im.convert('RGB').save(b,'JPEG',quality=95)
        return b.getvalue()
    except Exception:raise HTTPException(400,'参考图需为有效图片，单边240–8000像素，文件不超过10MB')


def store_asset(request,raw,name):
    data=jpeg(raw);uid=str(uuid.uuid4());p=root(request)/'video_assets'/uid
    real.save(p,{'id':uid,'name':name[:100],'created_at':time.time()});(p/'image.jpg').write_bytes(data)
    return {'id':uid,'name':name[:100],'url':f'/api/demo/wan/assets/{uid}/image'}


@router.post('/api/demo/wan/assets')
async def upload_asset(request:Request,image:UploadFile=File(...)):
    return store_asset(request,await image.read(10*1024*1024+1),image.filename or '角色参考')


class ImportAsset(BaseModel):
    frame_id:uuid.UUID|None=None
    video_id:uuid.UUID|None=None
    name:str=Field(default='角色参考',max_length=100)


@router.post('/api/demo/wan/assets/import')
def import_asset(body:ImportAsset,request:Request):
    if body.frame_id:p=real.frame_path(request,str(body.frame_id))/'keyframe.jpg'
    elif body.video_id:p=real.folder(request,str(body.video_id))/'keyframe.jpg'
    else:raise HTTPException(400,'请选择参考关键帧')
    if not p.is_file():raise HTTPException(404,'参考关键帧不存在')
    return store_asset(request,p.read_bytes(),body.name)


@router.get('/api/demo/wan/assets/{asset_id}/image')
def asset_image(asset_id:str,request:Request):
    p=root(request)/'video_assets'/ident(asset_id)/'image.jpg'
    if not p.is_file():raise HTTPException(404,'参考图不存在')
    return FileResponse(p,media_type='image/jpeg')


def last_frame(request,video_id):
    path=real.folder(request,str(video_id));data=real.read(path)
    if data['status']!='success' or not (path/'video.mp4').is_file():raise HTTPException(409,'前一镜头尚未完成')
    target=path/'continuity-last.jpg'
    with _LOCK:
        if not target.exists():
            try:
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-y','-sseof','-0.08','-i',str(path/'video.mp4'),'-frames:v','1',str(target)],check=True,capture_output=True,timeout=30)
                if not target.exists():raise ValueError()
            except (subprocess.SubprocessError,ValueError):raise HTTPException(409,'无法提取前一镜头的结束画面')
    return target.read_bytes()


def references(body,request):
    images=[];names=[]
    for item in body.references:
        p=root(request)/'video_assets'/str(item.asset_id)/'image.jpg'
        if not p.is_file():raise HTTPException(404,'角色参考图不存在，请重新上传')
        images.append(p.read_bytes());names.append('固定参考：'+item.name)
    if body.previous_video_id:
        images.append(last_frame(request,body.previous_video_id));names.append('前一镜头结束画面，保持空间、服装和动作衔接')
    elif body.previous_frame_id:
        p=real.frame_path(request,str(body.previous_frame_id))/'keyframe.jpg'
        if not p.is_file():raise HTTPException(409,'前一镜头关键帧尚未就绪')
        images.append(p.read_bytes());names.append('前一镜头关键帧，仅辅助空间、光线和动作衔接，固定参考仍是主体身份依据')
    return images,names


class BoardShot(BaseModel):
    id:int=Field(ge=1,le=999999)
    title:str=Field(default='',max_length=100)
    description:str=Field(default='',max_length=1200)
    camera:str=Field(default='固定',max_length=40)
    role_ids:list[str]=Field(default_factory=list,max_length=4)
    previous:int|None=None
    frame_id:uuid.UUID|None=None
    frame_signature:str=Field(default='',max_length=80)
    video_id:uuid.UUID|None=None
    video_signature:str=Field(default='',max_length=80)
    included:bool=True
    video_mode:Literal['first_frame','reference']='first_frame'
    changes:list[Annotated[str,Field(min_length=1,max_length=500)]]=Field(default_factory=list,max_length=8)
    confirmed_frame_id:uuid.UUID|None=None


class BoardRole(BaseModel):
    id:str=Field(max_length=60)
    name:str=Field(default='角色',max_length=80)
    description:str=Field(default='',max_length=600)
    asset_id:uuid.UUID|None=None


class BoardState(BaseModel):
    revision:int=Field(default=0,ge=0)
    story:str=Field(default='',max_length=4000)
    flow_input_signature:str=Field(default='',max_length=80)
    roles:list[BoardRole]=Field(default_factory=list,max_length=4)
    shots:list[BoardShot]=Field(default_factory=list,max_length=12)
    positions:dict[str,list[float]]=Field(default_factory=dict,max_length=60)
    merge_id:uuid.UUID|None=None


@router.get('/api/demo/wan/board')
def get_board(request:Request):
    p=root(request)/'video_board'/'manifest.json'
    if not p.exists():return {'board':None}
    return {'board':real.read(p.parent)}


@router.put('/api/demo/wan/board')
def put_board(body:BoardState,request:Request):
    ids=[s.id for s in body.shots];roles={r.id for r in body.roles}
    if len(set(ids))!=len(ids) or len(roles)!=len(body.roles):raise HTTPException(400,'节点编号不能重复')
    for i,s in enumerate(body.shots):
        if s.previous is not None and s.previous not in ids[:i]:raise HTTPException(400,'衔接只能指向更早的镜头，不能形成循环')
        if not set(s.role_ids)<=roles:raise HTTPException(400,'连接了不存在的角色节点')
    if any(len(v)!=2 or any(not(-10000<=x<=20000) for x in v) for v in body.positions.values()):raise HTTPException(400,'节点位置无效')
    path=root(request)/'video_board'
    with _LOCK:
        prior=real.read(path) if (path/'manifest.json').exists() else {'revision':0}
        if prior['revision']!=body.revision:raise HTTPException(409,'画布已在其他窗口修改，请刷新载入后再编辑')
        result=body.model_dump(mode='json');result['revision']+=1;real.save(path,result)
    return {'board':result}


class MergeInput(BaseModel):
    request_id:uuid.UUID
    ids:list[uuid.UUID]=Field(min_length=2,max_length=12)
    project:str=Field(default='我的创作项目',max_length=60)
    ratio:Literal['16:9','9:16','1:1']='16:9'
    resolution:Literal['480P','720P','1080P']='480P'


def output_size(ratio, resolution):
    short, long = {'480P': (480, 854), '720P': (720, 1280), '1080P': (1080, 1920)}[resolution]
    return (short, short) if ratio == '1:1' else (short, long) if ratio == '9:16' else (long, short)


def merge_folder(request,value):return root(request)/'video_merges'/ident(value)


def compose(path,clips):
    data=real.read(path);normalized=[];ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    width, height = data.get('width', 854), data.get('height', 480)
    try:
        for index,clip in enumerate(clips):
            output=path/f'part-{index}.mp4'
            # First iteration deliberately exports a silent timeline, explicitly labelled in UI.
            subprocess.run([ffmpeg,'-v','error','-y','-i',str(clip),'-map','0:v:0','-an','-vf',
                f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30',
                '-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',str(output)],check=True,capture_output=True,timeout=180)
            normalized.append(output);data['completed_clips']=index+1;real.save(path,data)
        listing=path/'concat.txt';listing.write_text('\n'.join(f"file '{p.name}'" for p in normalized))
        subprocess.run([ffmpeg,'-v','error','-y','-f','concat','-safe','1','-i',str(listing),'-c','copy','-movflags','+faststart',str(path/'film.mp4')],check=True,capture_output=True,timeout=180)
        if (path/'film.mp4').stat().st_size<64:raise ValueError()
        reader=imageio_ffmpeg.read_frames(str(path/'film.mp4'))
        try:metadata=next(reader)
        finally:reader.close()
        data.update(status='success',completed_at=time.time(),audio=False,duration=metadata['duration'])
    except (OSError,ValueError,subprocess.SubprocessError):
        data.update(status='failed',error='成片合并失败，原镜头保留，可重试合并。')
    finally:
        for p in normalized:p.unlink(missing_ok=True)
        real.save(path,data)
        with _LOCK:_MERGING.discard(str(path))


@router.post('/api/demo/wan/merges')
def create_merge(body:MergeInput,request:Request):
    path=merge_folder(request,body.request_id)
    with _LOCK:
        if (path/'manifest.json').exists():return real.read(path)
        clips=[];sources=[]
        for uid in body.ids:
            source=real.folder(request,str(uid));d=real.read(source)
            if d['status']!='success' or not (source/'video.mp4').is_file():raise HTTPException(409,'包含未完成或文件缺失的镜头')
            clips.append(source/'video.mp4');sources.append({'id':str(uid),'shot':d['shot'],'task_id':d.get('task_id'),'duration':d.get('usage',{}).get('output_video_duration',d.get('duration',5))})
        width, height = output_size(body.ratio, body.resolution)
        data={'id':str(body.request_id),'status':'merging','project':body.project,'sources':sources,'created_at':time.time(),
              'duration':sum(s['duration'] for s in sources),'completed_clips':0,'resolution':f'{width}x{height}',
              'width':width,'height':height,'ratio':body.ratio,'fps':30,'audio':False}
        real.save(path,data);_MERGING.add(str(path));threading.Thread(target=compose,args=(path,clips),daemon=True).start()
    return data


@router.get('/api/demo/wan/merges/{merge_id}')
def get_merge(merge_id:str,request:Request):
    path=merge_folder(request,merge_id);data=real.read(path)
    if data['status']=='merging' and str(path) not in _MERGING:
        data.update(status='failed',error='服务重启中断了合并，可重新合并，原镜头未更改。');real.save(path,data)
    return data


@router.get('/api/demo/wan/merges/{merge_id}/video')
def merged_video(merge_id:str,request:Request):
    path=merge_folder(request,merge_id)
    if real.read(path)['status']!='success' or not (path/'film.mp4').is_file():raise HTTPException(409,'成片尚未就绪')
    return FileResponse(path/'film.mp4',media_type='video/mp4',filename='story-film.mp4')
