"""Isolated browser QA: PYTHONPATH=. .venv/bin/python tests/ui_fixture_server.py"""
import io
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from PIL import Image
from aiside.demo import router
from aiside.video_demo import router as video_router
from aiside.settings import ROOT_DIR, Settings

class FixtureProvider:
    name='seedream'
    model_draft='TEST_ONLY'
    failing=True
    calls=0
    def inpaint(self, **kw):
        self.calls+=1
        time.sleep(.5)
        if self.failing: raise RuntimeError('测试环境模拟失败，可重试')
        buf=io.BytesIO();Image.new('RGB',(1024,1024),'#b1ceda').save(buf,format='PNG')
        return SimpleNamespace(data=buf.getvalue())

app=FastAPI()
app.state.settings=Settings(data_dir=Path(tempfile.mkdtemp(prefix='studio-browser-qa-')))
app.state.provider=FixtureProvider()
app.include_router(router);app.include_router(video_router)
@app.post('/qa/recover')
def recover():
    app.state.provider.failing=False
    return {'calls':app.state.provider.calls}
app.mount('/',StaticFiles(directory=ROOT_DIR/'web',html=True))
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8876)
