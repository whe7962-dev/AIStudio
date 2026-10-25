"""Isolated local UI fixture. Never imports or calls paid providers. Run manually on 8791."""
import base64
import io
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import imageio_ffmpeg
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from aiside import video_real as real, video_workflow as wf, ad_prompts, demo
from aiside.settings import Settings, ROOT_DIR

root=Path(tempfile.mkdtemp(prefix='ad-frontend-ui-'))
metrics={'frames':[],'videos':[],'fail_next':False}
class Provider:
    name='ui-fixture'
    def generate(self,**kwargs):
        metrics['frames'].append({'width':kwargs['width'],'height':kwargs['height'],'references':len(kwargs.get('anchor_refs',[])),'prompt':kwargs['prompt']})
        if metrics['fail_next']:
            metrics['fail_next']=False
            raise RuntimeError('Intentional UI test failure')
        raw=base64.b64decode(kwargs['anchor_refs'][0].split(',',1)[1])
        with Image.open(io.BytesIO(raw)) as im:
            out=ImageOps.pad(im.convert('RGB'),(kwargs['width'],kwargs['height']),color='#edf0f4');b=io.BytesIO();out.save(b,'JPEG')
        return SimpleNamespace(data=b.getvalue())

def fake_start(path,base,key,model,submit=False):
    def work():
        data=real.read(path);metrics['videos'].append({k:data.get(k) for k in ['id','ratio','resolution','duration','references']});data.update(status='generating',task_id='test-'+path.name);real.save(path,data)
        width,height=wf.output_size(data['ratio'],data['resolution'])
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y','-loop','1','-i',str(path/'keyframe.jpg'),'-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2','-t','0.5','-r','24','-c:v','libx264','-pix_fmt','yuv420p',str(path/'video.mp4')],check=True)
        data.update(status='success',generated_by_model=False,usage={'output_video_duration':.5});real.save(path,data);real._RUNNING.discard(str(path))
    real._RUNNING.add(str(path));threading.Thread(target=work,daemon=True).start()
real.config=lambda:('https://unit.invalid/v1','ui-test-no-key','wan3.0-video-prime')
real.start=fake_start
app=FastAPI();app.state.settings=Settings(data_dir=root,config_dir=ROOT_DIR/'config',provider='stub');app.state.provider=Provider()
for router in [real.router,wf.router,ad_prompts.router,demo.router]:app.include_router(router)
@app.get('/__test/metrics')
def get_metrics():return metrics
@app.post('/__test/fail-next')
def fail_next():metrics['fail_next']=True;return {'ok':True}
app.mount('/',StaticFiles(directory=ROOT_DIR/'web',html=True),name='web')
if __name__=='__main__':
    print('Isolated test data:',root,flush=True)
    uvicorn.run(app,host='127.0.0.1',port=8791,log_level='warning')
