"""Build owned, synthetic local demo clips. No model or network inference.
Optional development dependency: imageio-ffmpeg. Runtime serves prebuilt files.
"""
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

OUT = Path(__file__).resolve().parents[1] / 'web/assets/prototype'
OUT.mkdir(parents=True, exist_ok=True)
W,H,FPS,SECONDS = 960,540,24,4
fontpath='/System/Library/Fonts/Supplemental/Arial.ttf'
font=ImageFont.truetype(fontpath,22)
small=ImageFont.truetype(fontpath,16)

def frame(shot,t):
    im=Image.new('RGB',(W,H),['#d8e2e9','#e7ded0','#cddcdb'][shot-1])
    d=ImageDraw.Draw(im)
    d.rectangle((0,390,W,H),fill=['#b7c7d2','#c9b8a0','#9ab4b1'][shot-1])
    # A deliberately schematic mini-story: meeting, message, departure.
    for x in [80,720]:
        d.rounded_rectangle((x,75,x+150,330),12,fill='#f0f3f3',outline='#9caeb7',width=5)
        d.line((x+75,75,x+75,330),fill='#bac5ca',width=5)
    def person(x,y,color):
        d.ellipse((x-23,y-92,x+23,y-46),fill='#d8ad90')
        d.rounded_rectangle((x-34,y-40,x+34,y+75),16,fill=color)
        d.line((x-17,y+73,x-23,y+140),fill=color,width=18)
        d.line((x+17,y+73,x+23,y+140),fill=color,width=18)
    if shot==1:
        person(380+int(t*12),290,'#43647c'); person(600,290,'#916e66')
    elif shot==2:
        person(370,290,'#43647c'); person(600,290,'#916e66')
        d.rectangle((454+int(t*8),320,530+int(t*8),366),fill='#fcf8ee',outline='#8a8174',width=2)
        d.line((454+int(t*8),320,492+int(t*8),347,530+int(t*8),320),fill='#8a8174',width=2)
    else:
        person(340+int(t*34),290,'#43647c'); person(650,290,'#916e66')
    d.rounded_rectangle((20,18,385,61),8,fill='#fdf3dc')
    d.text((34,28),'PROTOTYPE / LOCAL SAMPLE',font=font,fill='#825c20')
    d.text((24,491),f'SHOT {shot:02d}  |  DEMO ONLY  |  {t:04.1f}s',font=small,fill='#263a47')
    return im

for shot in [1,2,3]:
    frame(shot,1.5).save(OUT/f'keyframe-{shot}.jpg',quality=90)
    path=OUT/f'shot-{shot}.mp4'
    proc=subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(),'-y','-f','rawvideo','-vcodec','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-an','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],stdin=subprocess.PIPE,stderr=subprocess.DEVNULL)
    for i in range(SECONDS*FPS): proc.stdin.write(frame(shot,i/FPS).tobytes())
    proc.stdin.close()
    if proc.wait(): raise SystemExit('Video encoding failed')
    print(path.name,path.stat().st_size)
(OUT/'README.txt').write_text('AIStudio 本地视频原型素材\n这些 MP4 和关键帧由 scripts/build_prototype_media.py 用几何图形程序化绘制并编码，非模型生成，无外部素材。\n每段 4 秒，960×540，24fps，H.264，无音轨；仅用于播放与导出流程验证。\n',encoding='utf-8')
