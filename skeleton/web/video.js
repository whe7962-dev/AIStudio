(() => {
  const $=id=>document.getElementById(id);
  const defaults=[{id:1,description:'车站窗边，两位旧友重逢，欲言又止。',camera:'固定'},{id:2,description:'一封信被轻轻推到桌面，交代故事转折。',camera:'缓推'},{id:3,description:'一人转身离开，另一人停在原地。',camera:'跟随'}];
  let state={shots:structuredClone(defaults),selected:[1,2,3],frames:false,ready:false,reference:'',status:'idle',stage:null,progress:0};
  let busy=false, timer=null, activeClip=1, exportBusy=false;
  try { const saved=JSON.parse(Studio.read('studio.video')||'null'); if(saved && Array.isArray(saved.shots) && saved.shots.length===3 && saved.shots.every((s,i)=>s.id===i+1 && typeof s.description==='string')) state={...state,...saved}; } catch (_) {}
  if(state.status==='generating') { state.status='interrupted'; state.ready=false; }
  function persist(){ Studio.store('studio.video',JSON.stringify(state)); Studio.setVideoState(structuredClone(state)); }
  function status(text,error=false){$('videoStatus').textContent=text;$('videoStatus').className=error?'error-message':'hint';}
  function queue(){ Studio.updateJob({id:'video:prototype',type:'video',name:state.stage==='frames'?'示例关键帧（模拟）':'示例视频（模拟）',status:state.status,progress:state.progress}); }
  function controls(){
    $('keyframeGenerate').disabled=busy; $('videoReset').disabled=busy;
    $('videoReference').disabled=busy; $('simulateVideoFailure').disabled=busy;
    $('videoGenerate').disabled=busy || !state.frames || !state.selected.length;
    $('videoSingleExport').disabled=exportBusy || busy || !state.ready;
    $('videoAllExport').disabled=exportBusy || busy || !state.ready;
    $('videoRetry').hidden=!['failed','interrupted'].includes(state.status);
    $('videoRetry').disabled=busy;
    $('videoProgress').hidden=!busy; $('videoProgress').value=state.progress;
    document.querySelectorAll('#storyRows textarea,#storyRows select,#keyframes input').forEach(el=>el.disabled=busy);
  }
  function invalidate(){
    state.ready=false; state.frames=false; state.status='idle'; state.progress=0;
    $('samplePlayer').pause(); $('samplePlayer').removeAttribute('src'); $('samplePlayer').load();
    renderFrames(); renderPlayer(); persist(); controls(); status('分镜已修改，请重新生成示例关键帧。');
  }
  function renderRows(){
    $('storyRows').replaceChildren();
    state.shots.forEach(shot=>{
      const row=document.createElement('tr');
      const id=document.createElement('td');id.textContent=String(shot.id).padStart(2,'0');
      const desc=document.createElement('td');const input=document.createElement('textarea');input.maxLength=500;input.value=shot.description;input.setAttribute('aria-label','镜头'+shot.id+'描述');input.oninput=()=>{shot.description=input.value;invalidate();};desc.append(input);
      const cam=document.createElement('td');const select=document.createElement('select');select.setAttribute('aria-label','镜头'+shot.id+'运镜');['固定','缓推','跟随'].forEach(v=>select.add(new Option(v,v)));select.value=shot.camera;select.onchange=()=>{shot.camera=select.value;invalidate();};cam.append(select);
      const duration=document.createElement('td');duration.textContent='4秒';row.append(id,desc,cam,duration);$('storyRows').append(row);
    });
  }
  function renderReferences(){
    const select=$('videoReference');select.replaceChildren(new Option('不选参考，使用本地示例',''));
    Studio.assets().filter(a=>a.kind!=='keyframe').forEach(a=>select.add(new Option(a.name,a.id)));
    if(state.reference && [...select.options].some(o=>o.value===state.reference)) select.value=state.reference;
    else if(state.reference) { state.reference=''; persist(); }
    const asset=Studio.assets().find(a=>a.id===state.reference);
    $('videoRefBox').hidden=!asset;
    if(asset) $('videoRefPreview').src=asset.url;
  }
  $('videoReference').onchange=()=>{state.reference=$('videoReference').value;renderReferences();persist();};
  window.addEventListener('studio:assets',renderReferences);
  function renderFrames(){
    const box=$('keyframes');box.replaceChildren();
    if(!state.frames){const empty=document.createElement('p');empty.className='empty';empty.textContent='先生成示例关键帧，再选择要演示的镜头。';box.append(empty);return;}
    state.shots.forEach(shot=>{
      const card=document.createElement('label');card.className='keyframe-card';
      const img=document.createElement('img');img.src='/assets/prototype/keyframe-'+shot.id+'.jpg';img.alt='镜头'+shot.id+'本地示例关键帧';
      const line=document.createElement('span');const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=state.selected.includes(shot.id);checkbox.setAttribute('aria-label','选择镜头'+shot.id);
      checkbox.onchange=()=>{state.selected=checkbox.checked?[...state.selected,shot.id].sort():state.selected.filter(id=>id!==shot.id);state.ready=false;renderPlayer();persist();controls();status(state.selected.length?'已选择 '+state.selected.length+' 个镜头，点击生成示例视频。':'至少选择一个镜头才能继续。');};
      line.append(checkbox,document.createTextNode(' 镜头 '+shot.id+' · 本地示例'));card.append(img,line);box.append(card);
    });
  }
  function renderPlayer(){
    $('clipControls').hidden=!state.ready;$('samplePlayer').hidden=!state.ready;$('videoEmpty').hidden=state.ready;
    if(!state.ready){$('samplePlayer').pause();return;}
    $('clipSelect').replaceChildren();state.selected.forEach(id=>$('clipSelect').add(new Option('镜头 '+id+' · 本地示例 · 4秒',String(id))));
    if(!state.selected.includes(activeClip)) activeClip=state.selected[0];
    $('clipSelect').value=String(activeClip); loadClip();
  }
  function loadClip(){
    activeClip=Number($('clipSelect').value); $('samplePlayer').poster='/assets/prototype/keyframe-'+activeClip+'.jpg';
    $('samplePlayer').src='/assets/prototype/shot-'+activeClip+'.mp4';$('samplePlayer').load();
  }
  $('clipSelect').onchange=loadClip;
  $('samplePlayer').addEventListener('error',()=>{if(!state.ready)return;state.ready=false;state.status='failed';state.stage='video';persist();queue();controls();status('本地示例视频加载失败，请检查服务后重试。',true);});
  async function run(stage){
    if(busy) return;
    if(stage==='frames' && state.shots.some(s=>!s.description.trim())){status('请填写每个镜头的画面描述。',true);return;}
    if(stage==='video' && (!state.frames || !state.selected.length)){status('请先生成关键帧并选择至少一个镜头。',true);return;}
    busy=true;state.stage=stage;state.status='generating';state.progress=0;state.ready=false;
    if(stage==='frames')state.frames=false;
    const fail=$('simulateVideoFailure').checked;$('simulateVideoFailure').checked=false;
    renderFrames();renderPlayer();persist();controls();queue();
    status('模拟处理中… 不调用视频模型。');
    timer=setInterval(async()=>{
      state.progress=Math.min(95,state.progress+20);controls();queue();
      if(state.progress<95) return;
      clearInterval(timer);timer=null;
      try {
        if(fail)throw new Error('本次为人为模拟失败；点击重试可继续。');
        const urls=stage==='frames'?state.shots.map(s=>'/assets/prototype/keyframe-'+s.id+'.jpg'):state.selected.map(id=>'/assets/prototype/shot-'+id+'.mp4');
        const responses=await Promise.all(urls.map(url=>fetch(url,{method:'HEAD'})));
        if(responses.some(r=>!r.ok))throw new Error('本地示例素材缺失，请检查服务后重试。');
        if(stage==='frames'){
          state.frames=true;
          Studio.addAssets(state.shots.map(s=>({id:'keyframe:'+s.id,name:'镜头'+s.id+' · 示例关键帧',url:'/assets/prototype/keyframe-'+s.id+'.jpg',kind:'keyframe'})));
        } else state.ready=true;
        state.status='prototype';state.progress=100;
        status(stage==='frames'?'示例关键帧就绪。选择镜头后继续；内容未由模型生成。':'本地示例视频就绪，可播放并导出。视频能力仍为原型 / 验证中。');
      }catch(e){state.status='failed';status(e.message,true);}
      finally{busy=false;renderFrames();renderPlayer();persist();controls();queue();}
    },450);
  }
  $('keyframeGenerate').onclick=()=>run('frames');$('videoGenerate').onclick=()=>run('video');$('videoRetry').onclick=()=>run(state.stage||'frames');
  $('videoReset').onclick=()=>{state.shots=structuredClone(defaults);state.selected=[1,2,3];renderRows();invalidate();};
  async function exportMedia(all){
    if(exportBusy||busy||!state.ready)return;
    exportBusy=true;controls();Studio.notice('');
    try{
      const response=all?await fetch('/api/demo/video/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project:Studio.project(),reference_asset:state.reference,shots:state.shots.filter(s=>state.selected.includes(s.id))})}):await fetch('/assets/prototype/shot-'+activeClip+'.mp4');
      if(!response.ok){let message='导出失败，请稍后重试';try{message=(await response.json()).detail||message;}catch(_){}throw new Error(typeof message==='string'?message:'导出参数无效');}
      Studio.downloadBlob(await response.blob(),all?'video-prototype.zip':'prototype-shot-'+activeClip+'.mp4');
      status('已导出'+(all?'原型演示包':'本地示例 MP4')+'，非模型生成内容。');
    }catch(e){status(e.message,true);Studio.notice('视频原型导出失败：'+e.message);}
    finally{exportBusy=false;controls();}
  }
  $('videoSingleExport').onclick=()=>exportMedia(false);$('videoAllExport').onclick=()=>exportMedia(true);
  renderRows();renderReferences();renderFrames();renderPlayer();controls();persist();
  if(state.frames)Studio.addAssets(state.shots.map(s=>({id:'keyframe:'+s.id,name:'镜头'+s.id+' · 示例关键帧',url:'/assets/prototype/keyframe-'+s.id+'.jpg',kind:'keyframe'})));
  if(state.status!=='idle')queue();
  if(state.status==='interrupted')status('上次模拟任务被中断，可点击重试。',true);
  else if(state.ready)status('已恢复本地视频原型。示例可播放、导出，真实视频能力待验证。');
  window.addEventListener('beforeunload',e=>{if(busy){e.preventDefault();e.returnValue='';}});
})();
