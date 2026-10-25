/* Real video workflow; isolated from the retained local prototype. */
(() => {
  const $=id=>document.getElementById(id);
  const defaults=[{id:1,description:'车站窗边，两位成年旧友重逢，欲言又止。',camera:'固定'},
    {id:2,description:'暖色灯光下的木桌特写，一只成年人的手将未拆开的信缓缓推到桌面中央。',camera:'缓推'},
    {id:3,description:'车站大厅，一位成年人转身离开，另一位站在原地目送。',camera:'跟随'}];
  let state={shots:structuredClone(defaults),frames:{},jobs:[],activeJob:'',shot:1,frameTask:null,videoMode:'real'};
  try{const saved=JSON.parse(Studio.read('studio.realVideo')||'null');if(saved?.shots?.length===3)state={...state,...saved};}catch(_){}
  let busy=false,configured=false,exporting=false,pollTimer=null,frameTimer=null;
  const terminal=new Set(['success','failed','submission_unknown','download_failed','query_error']);
  const labels={submitting:'提交中',generating:'生成中',downloading:'下载中',success:'已完成',failed:'失败',submission_unknown:'提交待核对',download_failed:'下载失败',query_error:'查询待恢复'};
  function persist(){Studio.store('studio.realVideo',JSON.stringify(state));}
  function status(message,error=false){$('realStatus').textContent=message;$('realStatus').className=error?'error-message':'hint';}
  async function api(url,options={}){const r=await fetch(url,options);if(!r.ok){let e;try{e=(await r.json()).detail;}catch(_){}const error=new Error(typeof e==='string'?e:'请求失败（'+r.status+'）');error.status=r.status;throw error;}return r.json();}
  function post(body){return {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};}
  function selected(){return state.shots.find(s=>s.id===Number(state.shot));}
  function current(){return state.jobs.find(j=>j.id===state.activeJob);}
  function mode(next){state.videoMode=next;$('realVideoPanel').hidden=next!=='real';$('prototypeVideoPanel').hidden=next==='real';$('realExports').hidden=next!=='real';$('prototypeExports').hidden=next==='real';$('realMode').className=next==='real'?'':'secondary';$('prototypeMode').className=next==='real'?'secondary':'';persist();}
  $('realMode').onclick=()=>mode('real');$('prototypeMode').onclick=()=>mode('prototype');
  function controls(){
    $('realFrameGenerate').disabled=busy||!configured;$('realGenerate').disabled=busy||!configured||!state.frames[state.shot];
    $('realShot').disabled=busy;$('realReference').disabled=busy;
    document.querySelectorAll('#realStoryRows textarea,#realStoryRows select,#realFrames button').forEach(e=>e.disabled=busy);
    const j=current();$('realSingleExport').disabled=exporting||j?.status!=='success';
    $('realAllExport').disabled=exporting||!state.jobs.some(j=>j.status==='success');
    $('realResume').hidden=!j||!['query_error','download_failed'].includes(j.status);$('realResume').disabled=busy;
  }
  function queue(j){Studio.updateJob({id:'wan:'+j.id,type:'video',real:true,name:'镜头'+j.shot+' · '+j.model,status:labels[j.status]||j.status,progress:j.status==='success'?100:null});}
  function renderRows(){
    $('realStoryRows').replaceChildren();
    state.shots.forEach(s=>{const row=document.createElement('tr');const id=document.createElement('td');id.textContent=s.id;
      const desc=document.createElement('td');const input=document.createElement('textarea');input.maxLength=500;input.value=s.description;input.setAttribute('aria-label','真实镜头'+s.id+'描述');input.oninput=()=>{s.description=input.value;delete state.frames[s.id];persist();renderFrames();controls();status('分镜已修改，该镜头需要重新生成关键帧。');};desc.append(input);
      const cam=document.createElement('td');const select=document.createElement('select');['固定','缓推','跟随'].forEach(x=>select.add(new Option(x,x)));select.value=s.camera;select.setAttribute('aria-label','真实镜头'+s.id+'运镜');select.onchange=()=>{s.camera=select.value;delete state.frames[s.id];persist();renderFrames();controls();status('分镜已修改，该镜头需要重新生成关键帧。');};cam.append(select);
      const dur=document.createElement('td');dur.textContent='5秒';row.append(id,desc,cam,dur);$('realStoryRows').append(row);});
    $('realShot').value=String(state.shot);
  }
  function renderFrames(){
    const box=$('realFrames');box.replaceChildren();
    state.shots.forEach(s=>{const button=document.createElement('button');button.type='button';button.setAttribute('aria-label','选择真实镜头'+s.id);button.setAttribute('aria-pressed',String(state.shot===s.id));
      const f=state.frames[s.id];if(f){const img=document.createElement('img');img.src=f.url;img.alt='镜头'+s.id+'真实关键帧';button.append(img);}
      button.append(document.createTextNode('镜头'+s.id+(f?' · 已生成':' · 待生成')));button.onclick=()=>{state.shot=s.id;$('realShot').value=String(s.id);persist();renderFrames();controls();};box.append(button);});
  }
  function refs(){const select=$('realReference'),previous=select.value;select.replaceChildren(new Option('按分镜描述生成关键帧',''));Studio.assets().filter(a=>a.kind==='upload'||a.kind==='image').forEach(a=>select.add(new Option(a.name,a.id)));if([...select.options].some(o=>o.value===previous))select.value=previous;}
  window.addEventListener('studio:assets',refs);
  $('realShot').onchange=()=>{state.shot=Number($('realShot').value);persist();renderFrames();controls();};
  async function dataURL(url){const response=await fetch(url);if(!response.ok)throw new Error('参考图片加载失败');const blob=await response.blob();return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('参考图片读取失败'));reader.readAsDataURL(blob);});}
  function frameQueue(data){Studio.updateJob({id:'wan-frame:'+data.id,type:'video',real:true,name:'镜头'+data.shot+' · 真实关键帧',status:data.status,progress:data.status==='success'?100:null});}
  async function pollFrame(){
    if(!state.frameTask)return;
    try{const data=await api('/api/demo/wan/keyframes/'+state.frameTask);frameQueue(data);
      if(data.status==='success'){const f={id:data.id,url:'/api/demo/wan/keyframes/'+data.id+'/image'};state.frames[data.shot]=f;state.frameTask=null;busy=false;persist();renderFrames();Studio.addAssets([{id:'wan-frame:'+f.id,name:'镜头'+data.shot+' · 真实关键帧',url:f.url,kind:'real-keyframe'}]);status('关键帧已由图片模型生成。选择该镜头后，可生成真实视频。');controls();return;}
      if(data.status==='failed'){state.frameTask=null;persist();throw new Error(data.error||'关键帧生成失败');}
      status('正在生成真实关键帧…');frameTimer=setTimeout(pollFrame,2000);
    }catch(e){if(e.status===404){state.frameTask=null;persist();}busy=false;status(e.message+(state.frameTask?'；可点击关键帧按钮重新查询。':'；可重新生成关键帧。'),true);controls();}
  }
  $('realFrameGenerate').onclick=async()=>{
    if(busy)return;
    if(state.frameTask){busy=true;controls();await pollFrame();return;}
    const shot=selected();if(!shot.description.trim()){status('请填写当前镜头描述。',true);return;}
    busy=true;controls();status('正在提交真实关键帧任务…');
    try{const a=Studio.assets().find(a=>a.id===$('realReference').value);const image=a?await dataURL(a.url):'';
      state.frameTask=crypto.randomUUID();persist();
      const data=await api('/api/demo/wan/keyframes',post({request_id:state.frameTask,project:Studio.project(),shot:shot.id,prompt:shot.description+' 运镜：'+shot.camera,image}));frameQueue(data);await pollFrame();
    }catch(e){busy=false;status(e.message+'；未自动重新提交。',true);controls();}
  };
  function renderHistory(){
    const select=$('realHistory');select.replaceChildren();if(!state.jobs.length)select.add(new Option('暂无真实视频',''));
    [...state.jobs].reverse().forEach(j=>select.add(new Option('镜头'+j.shot+' · '+(labels[j.status]||j.status)+' · '+j.id.slice(0,8),j.id)));
    select.value=state.activeJob;
    const j=current();$('realPlayer').hidden=j?.status!=='success';$('realVideoEmpty').hidden=j?.status==='success';
    if(j?.status==='success'){const url='/api/demo/wan/jobs/'+j.id+'/video';if($('realPlayer').getAttribute('src')!==url){$('realPlayer').src=url;$('realPlayer').load();}}
    else{$('realPlayer').pause();}
    controls();
  }
  $('realHistory').onchange=()=>{state.activeJob=$('realHistory').value;persist();renderHistory();};
  function update(data){const index=state.jobs.findIndex(j=>j.id===data.id);if(index<0)state.jobs.push(data);else state.jobs[index]=data;persist();queue(data);renderHistory();}
  async function pollJob(id){
    try{const data=await api('/api/demo/wan/jobs/'+id);update(data);
      if(terminal.has(data.status)){busy=false;status(data.status==='success'?'真实视频已生成并保存本机，可播放和导出。内容质量仍待评测。':data.error||'任务未完成',data.status!=='success');controls();return;}
      busy=true;controls();status('真实视频'+(labels[data.status]||data.status)+' · 远端状态：'+(data.provider_status||'等待响应'));
      pollTimer=setTimeout(()=>pollJob(id),3000);
    }catch(e){busy=false;status(e.message+'；保留原任务，刷新页面继续查询，未重新生成。',true);const j=state.jobs.find(j=>j.id===id);if(j)update({...j,status:'query_error'});controls();}
  }
  $('realGenerate').onclick=async()=>{
    if(busy)return;const frame=state.frames[state.shot];if(!frame)return;
    const pending=state.jobs.find(j=>!terminal.has(j.status)||['submission_unknown','query_error','download_failed'].includes(j.status));
    if(pending){state.activeJob=pending.id;persist();status('已有未确认任务，请先查询或核对平台记录，避免重复计费。',true);renderHistory();return;}
    busy=true;controls();status('正在提交真实视频任务…');
    try{const shot=selected(),image=await dataURL(frame.url);const id=crypto.randomUUID();state.activeJob=id;update({id,shot:shot.id,status:'submitting',model:'wan3.0-video-prime'});
      const data=await api('/api/demo/wan/jobs',post({request_id:id,project:Studio.project(),shot:shot.id,prompt:shot.description+'。运镜：'+shot.camera+'。保持首帧人物和场景一致，动作自然，无字幕。',image}));update(data);await pollJob(id);
    }catch(e){busy=false;status(e.message+'；请重新查询原任务确认提交结果。',true);const j=current();if(j)update({...j,status:'query_error'});controls();}
  };
  $('realResume').onclick=async()=>{const j=current();if(!j||busy)return;busy=true;controls();try{await api('/api/demo/wan/jobs/'+j.id+'/resume',{method:'POST'});await pollJob(j.id);}catch(e){busy=false;status(e.message,true);controls();}};
  async function exportVideo(all){if(exporting)return;exporting=true;controls();try{const j=current();const r=all?await fetch('/api/demo/wan/export',post({ids:state.jobs.filter(x=>x.status==='success').map(x=>x.id)})):await fetch('/api/demo/wan/jobs/'+j.id+'/video');if(!r.ok)throw new Error('导出失败，请检查任务状态后重试');Studio.downloadBlob(await r.blob(),all?'wan-real-videos.zip':'wan-real-shot-'+j.shot+'.mp4');status('真实模型视频已导出。');}catch(e){status(e.message,true);}finally{exporting=false;controls();}}
  $('realSingleExport').onclick=()=>exportVideo(false);$('realAllExport').onclick=()=>exportVideo(true);
  $('realPlayer').onerror=()=>status('真实视频文件播放失败，可尝试下载检查；原任务结果已保留。',true);
  window.addEventListener('studio:viewjob',e=>{if(e.detail.type!=='video')return;mode(e.detail.real?'real':'prototype');if(e.detail.id.startsWith('wan:')){state.activeJob=e.detail.id.slice(4);persist();renderHistory();}});
  renderRows();renderFrames();renderHistory();refs();mode(state.videoMode);
  Object.entries(state.frames).forEach(([shot,f])=>Studio.addAssets([{id:'wan-frame:'+f.id,name:'镜头'+shot+' · 真实关键帧',url:f.url,kind:'real-keyframe'}]));
  state.jobs.forEach(queue);
  Promise.all([api('/api/demo/wan/config'),api('/api/demo/wan/jobs'),api('/api/demo/wan/keyframes')]).then(([c,history,frames])=>{
    configured=c.configured;
    const saved=new Map(state.jobs.map(j=>[j.id,j]));history.jobs.forEach(j=>saved.set(j.id,j));state.jobs=[...saved.values()].sort((a,b)=>(a.created_at||0)-(b.created_at||0));
    if(!state.activeJob&&state.jobs.length)state.activeJob=state.jobs[state.jobs.length-1].id;
    frames.frames.filter(f=>f.status==='success').forEach(f=>{const shot=state.shots.find(s=>s.id===f.shot);if(shot&&!state.frames[f.shot]&&f.prompt===shot.description+' 运镜：'+shot.camera)state.frames[f.shot]={id:f.id,url:'/api/demo/wan/keyframes/'+f.id+'/image'};});
    persist();renderFrames();renderHistory();state.jobs.forEach(queue);
    Object.entries(state.frames).forEach(([shot,f])=>Studio.addAssets([{id:'wan-frame:'+f.id,name:'镜头'+shot+' · 真实关键帧',url:f.url,kind:'real-keyframe'}]));
    status(c.configured?'真实服务已配置：'+c.model+(current()?.status==='success'?'。已恢复真实视频，可播放和导出。':'。先生成当前镜头关键帧。'):'真实视频服务未配置。',!c.configured);
    controls();if(state.frameTask){busy=true;controls();pollFrame();}else{const j=state.jobs.find(j=>!terminal.has(j.status));if(j){busy=true;controls();pollJob(j.id);}}
  }).catch(e=>status(e.message,true));
})();
