/* Editable graph: lines are actual shared references, continuity inputs and export order. */
(() => {
  const Intent=window.VideoIntent;
  let drafts;try{drafts=new Map(JSON.parse(Studio.read('studio.changeDrafts')||'[]'));}catch(_){drafts=new Map();}
  const saveDrafts=()=>Studio.store('studio.changeDrafts',JSON.stringify([...drafts]));
  const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
  let board=null, jobs=new Map(), frames=new Map(), film=null, selected='story', modeValue='real';
  let zoom=.7, pan={x:20,y:20}, connection=null, configured=false, busy=0, saveTimer, saving=false, dirty=false, conflict=false;
  const statuses={success:'已完成',generating:'生成中',submitting:'提交中',downloading:'下载中',failed:'失败',submission_unknown:'待核对',query_error:'查询失败',download_failed:'下载失败',merging:'合并中'};
  const active=new Set(['generating','submitting','downloading','merging']);
  function message(text,error=false){$('graphStatus').textContent=text;$('graphStatus').className=error?'error-message':'hint';}
  async function api(url,options={}){const r=await fetch(url,options);if(!r.ok){let d;try{d=(await r.json()).detail;}catch(_){}const e=new Error(typeof d==='string'?d:'请求失败（'+r.status+'）');e.status=r.status;throw e;}return r.json();}
  const post=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const shot=id=>board.shots.find(s=>s.id===Number(id)), role=id=>board.roles.find(r=>r.id===id);
  function hash(value){let h=2166136261;for(const c of JSON.stringify(value)){h^=c.charCodeAt(0);h=Math.imul(h,16777619);}return (h>>>0).toString(16);}
  function signature(s,kind='frame'){const prev=shot(s.previous);const data={story:board.story,description:s.description,camera:s.camera,roles:board.roles.filter(r=>s.role_ids.includes(r.id)),previous:prev?{id:prev.id,description:prev.description,frame:prev.frame_id,video:prev.video_id}:null};if(s.changes?.length)data.changes=s.changes;if(kind==='video')data.video={frame:s.frame_id,mode:s.video_mode||'first_frame'};return hash(data);}
  function fresh(s,kind){const value=s[kind+'_signature'],prev=shot(s.previous);const own=!value||value===signature(s,kind)||value==='adopted:'+signature(s,kind);return own&&(!prev||fresh(prev,'frame')&&(!prev.video_signature||fresh(prev,'video')));}
  const frameURL=id=>'/api/demo/wan/keyframes/'+id+'/image';
  const assetURL=id=>'/api/demo/wan/assets/'+id+'/image';
  const videoURL=id=>'/api/demo/wan/jobs/'+id+'/video';
  function resultState(s,kind){const data=(kind==='frame'?frames:jobs).get(s[kind+'_id']);if(!data)return '待生成';if(!fresh(s,kind))return '输入已修改';return statuses[data.status]||data.status;}
  function changed(renderNow=true){dirty=true;Studio.store('studio.workflowDraft',JSON.stringify(board));clearTimeout(saveTimer);saveTimer=setTimeout(save,300);if(renderNow)render();}
  async function save(){if(saving||!dirty||conflict||!board)return;saving=true;dirty=false;const snapshot=JSON.parse(JSON.stringify(board));try{const r=await api('/api/demo/wan/board',{...post(snapshot),method:'PUT'});board.revision=r.board.revision;Studio.store('studio.workflowDraft',JSON.stringify(board));}catch(e){dirty=true;if(e.status===409)conflict=true;message(e.message+'。当前草稿仍保留在浏览器中。',true);}finally{saving=false;if(dirty&&!conflict)saveTimer=setTimeout(save,1500);}}
  function mode(next){modeValue=next;$('realVideoPanel').hidden=next!=='real';$('prototypeVideoPanel').hidden=next==='real';$('realExports').hidden=next!=='real';$('prototypeExports').hidden=next==='real';$('realMode').className=next==='real'?'':'secondary';$('prototypeMode').className=next==='real'?'secondary':'';}
  $('realMode').onclick=()=>mode('real');$('prototypeMode').onclick=()=>mode('prototype');
  function nodeInfo(id){const [kind,key]=id.split(':');return {kind,s:shot(key),r:role(key),key};}
  function currentShot(){return nodeInfo(selected).s;}
  function outputIds(){return board.shots.filter(s=>s.included).map(s=>s.video_id);}
  function filmCurrent(){return film?.status==='success'&&JSON.stringify(film.sources.map(s=>s.id))===JSON.stringify(outputIds());}
  function canMerge(){const included=board.shots.filter(s=>s.included);return included.length>=2&&included.every(s=>jobs.get(s.video_id)?.status==='success'&&fresh(s,'video'));}
  function controls(){
    const last=board.shots.at(-1);$('graphAddShot').hidden=stepCount()<3;$('graphAddShot').disabled=busy>0||conflict||board.shots.length>=12||!last||jobs.get(last.video_id)?.status!=='success'||!fresh(last,'video');$('graphAddRole').disabled=busy>0||board.roles.length>=4;
    $('graphMerge').hidden=stepCount()<3||board.shots.length<2;$('graphMerge').disabled=busy>0||!canMerge();$('graphFilmExport').disabled=!filmCurrent();
    $('realSingleExport').disabled=jobs.get(currentShot()?.video_id)?.status!=='success';$('realAllExport').disabled=!board.shots.some(s=>jobs.get(s.video_id)?.status==='success');
    $('graphInspector').querySelectorAll('[data-mutates]').forEach(e=>{e.disabled=busy>0||conflict;
      if(e.dataset.action==='合并成片')e.disabled=e.disabled||!canMerge();
      if(e.dataset.action==='生成关键帧')e.disabled=e.disabled||!configured||stepCount()<2;
      if(e.dataset.action==='生成镜头视频')e.disabled=e.disabled||!configured||frames.get(currentShot()?.frame_id)?.status!=='success'||currentShot()?.confirmed_frame_id!==currentShot()?.frame_id||!fresh(currentShot(),'frame');
    });
  }
  function transform(){ $('graphSurface').style.transform=`translate(${pan.x}px,${pan.y}px) scale(${zoom})`;$('graphZoomLabel').textContent=Math.round(zoom*100)+'%'; }
  function entrySignature(){return hash({story:board.story,roles:board.roles,shots:board.shots.map(s=>({id:s.id,description:s.description,role_ids:s.role_ids}))});}
  function stepCount(){return Intent.visibleSteps(board,frames,jobs,board.flow_input_signature===entrySignature(),s=>fresh(s,'frame'));}
  function phase(){return selected==='story'||selected.startsWith('role:')?1:selected==='merge'||selected.startsWith('video:')?3:2;}
  function position(id){return [{story:90,review:420,finish:750}[id],210];}
  function fit(){const w=$('graphViewport').clientWidth,h=$('graphViewport').clientHeight;zoom=Math.max(.45,Math.min(1,(w-60)/(stepCount()*330)));pan={x:20,y:Math.max(0,(h-480)/2)};transform();}
  function enterStep(step){
    if(step>stepCount())return;
    if(step===1)select('story');
    else if(step===2)select('frame:'+(currentShot()||board.shots.find(s=>!s.confirmed_frame_id)||board.shots[0]).id);
    else if(filmCurrent())select('merge');
    else select('video:'+(currentShot()||board.shots.find(s=>s.confirmed_frame_id===s.frame_id&&s.frame_id)||board.shots[0]).id);
  }
  function select(id){selected=id;renderNodes();renderInspector();controls();}
  function addElement(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
  function button(text,action,parent,secondary=false){const b=addElement('button',text,secondary?'secondary':'');b.type='button';b.dataset.mutates='true';b.dataset.action=text;b.onclick=action;parent.append(b);return b;}
  function renderNodes(){
    const nodes=$('graphNodes'),edges=$('graphEdges');nodes.replaceChildren();edges.replaceChildren();
    const count=stepCount(),names=['创作起点','画面确认','视频成片'],ids=['story','review','finish'];
    const hints=['写想法，参考图可选','先看画面，再继续','生成、播放和导出'];
    for(let i=0;i<count;i++){
      const id=ids[i],node=addElement('article',undefined,'graph-node flow-node'+(phase()===i+1?' selected':''));node.dataset.node=id;
      const [x,y]=position(id);node.style.left=x+'px';node.style.top=y+'px';
      const orb=addElement('button',String(i+1).padStart(2,'0'),'flow-orb');orb.setAttribute('aria-label','进入'+names[i]);orb.onclick=()=>enterStep(i+1);
      node.append(orb,addElement('h3',names[i]),addElement('p',hints[i]));
      if(i===0)node.append(addElement('span',board.roles.length?'已带入 '+board.roles.length+' 份参考':'从一句想法开始','flow-caption'));
      if(i===1)node.append(addElement('span',board.shots.filter(s=>s.confirmed_frame_id===s.frame_id&&s.frame_id&&fresh(s,'frame')).length+' 段画面已确认','flow-caption'));
      if(i===2)node.append(addElement('span',filmCurrent()?'成片可导出':'每次只生成选中这一段','flow-caption'));
      nodes.append(node);
      if(i){const a=position(ids[i-1]),path=document.createElementNS(NS,'path');path.setAttribute('d',`M ${a[0]+154} ${a[1]+44} C ${a[0]+230} ${a[1]-10},${x+5} ${y+100},${x+66} ${y+44}`);path.setAttribute('class','flow-connection');edges.append(path);}
    }
    if(count<3){const note=addElement('div',count===1?'确认想法后，展开画面节点':'确认画面后，展开视频节点','flow-next');note.style.left=(position(ids[count-1])[0]+15)+'px';note.style.top='420px';nodes.append(note);}
    $('graphTimeline').closest('.graph-timeline').hidden=count<3||board.shots.length<2;
  }
  function field(label,value,onInput,parent,multiline=false){const lab=addElement('label',label),input=addElement(multiline?'textarea':'input');input.value=value||'';input.setAttribute('aria-label',label);input.dataset.mutates='true';input.oninput=()=>{onInput(input.value);changed(false);renderNodes();renderTimeline();controls();};lab.append(input);parent.append(lab);return input;}
  function check(label,value,onChange,parent){const lab=addElement('label',undefined,'graph-check'),input=addElement('input');input.type='checkbox';input.checked=value;input.dataset.mutates='true';input.onchange=()=>{onChange(input.checked);changed();renderInspector();};lab.append(input,document.createTextNode(label));parent.append(lab);}
  function options(label,items,value,onChange,parent){const lab=addElement('label',label),select=addElement('select');items.forEach(([v,t])=>select.add(new Option(t,v)));select.value=String(value??'');select.setAttribute('aria-label',label);select.dataset.mutates='true';select.onchange=()=>onChange(select.value);lab.append(select);parent.append(lab);return select;}
  function renderChangeEditor(s,box){
    const panel=addElement('section',undefined,'intent-panel');box.append(panel);
    panel.append(addElement('p','角色、场景和风格自动沿用；这里只说要改什么。','hint'));
    if(!s.description)field('这个镜头发生什么',s.description,v=>s.description=v.slice(0,1200),panel,true);
    else panel.append(addElement('p','原动作：'+s.description,'intent-original'));
    const inherited=addElement('details');inherited.append(addElement('summary','查看自动沿用的设定'));
    inherited.append(addElement('p',board.story||'尚未填写全局设定'));
    Intent.rolesFor(board,s).forEach(r=>inherited.append(addElement('p',r.name+'：'+r.description)));
    inherited.append(addElement('p','衔接：'+(shot(s.previous)?.title||'独立镜头')));panel.append(inherited);
    const changes=s.changes||[];
    changes.forEach((text,i)=>{const row=addElement('div',undefined,'intent-change');row.append(addElement('span',(i+1)+'. '+text));button('撤销这条',()=>{s.changes.splice(i,1);s.confirmed_frame_id=null;changed();renderInspector();message('已撤销修改，原动作和其他要求仍保留。');},row,true);panel.append(row);});
    const label=addElement('label','这次只改什么'),input=addElement('textarea');input.value=drafts.get(s.id)||'';input.maxLength=500;input.placeholder='例如：递信慢一点，保持看着对方';input.setAttribute('aria-label','这次只改什么');input.dataset.mutates='true';label.append(input);panel.append(label);
    const preview=addElement('p',undefined,'hint');panel.append(preview);
    const showImpact=()=>{const related=Intent.affected(board,s.id).slice(1);preview.textContent=input.value.trim()?'只修改「'+s.title+'」。'+(related.length?'后续衔接需复核：'+related.map(x=>x.title||'镜头'+x.id).join('、')+'。':'')+'应用后先检查关键帧，再生成本镜头；不会自动重跑其他镜头。':'修改会追加保留；同一动作有冲突时，最新要求优先。';};
    input.oninput=()=>{drafts.set(s.id,input.value);saveDrafts();showImpact();};showImpact();
    button('应用本次修改',()=>{const text=input.value.trim();if(!text)return;if(changes.length>=8){message('已保留8条修改，请先撤销不再需要的要求。',true);return;}s.changes=[...changes,text];s.confirmed_frame_id=null;drafts.delete(s.id);saveDrafts();changed();renderInspector();message('已保存本次修改；基础设定和之前的要求已保留。先生成关键帧检查。');},panel);
    const composed=addElement('details');composed.append(addElement('summary','查看实际生成要求'),addElement('p',Intent.prompt(board,s),'intent-prompt'));panel.append(composed);
  }
  function renderInspector(){const box=$('graphInspector');box.replaceChildren();const {kind,s,r}=nodeInfo(selected);box.append(addElement('div',kind==='role'?'角色参考':kind==='merge'?'成片输出':kind==='story'?'第一步':kind==='video'?'视频成片':'画面确认','inspector-kind'));box.append(addElement('h3',kind==='story'?'创作起点':kind==='role'?r?.name||'角色':kind==='merge'?'合并成片':s?.title||'分镜'));
    if(kind==='story'){
      const first=board.shots[0];if(first)field('想生成怎样的一段视频',first.description,v=>first.description=v.slice(0,1200),box,true);
      const settings=addElement('details');settings.append(addElement('summary','共用场景与风格（可选）'));box.append(settings);field('故事 / 场景 / 整体风格',board.story,v=>board.story=v.slice(0,4000),settings,true);
      box.append(addElement('p','人物或商品参考（可选，后续自动沿用）','hint'));
      board.roles.forEach(r=>button(r.name+(r.asset_id?' · 已有参考':' · 添加图片'),()=>select('role:'+r.id),box,true));
      button('添加参考素材',()=>{if(board.roles.length<4)$('graphAddRole').click();},box,true);
      button('确认想法，展开画面',()=>{if(!first?.description.trim()){message('先写一句想生成的画面与动作。',true);return;}if(board.roles.some(r=>!r.asset_id)){message('请补齐参考图片，或删除空的参考素材。',true);return;}board.flow_input_signature=entrySignature();changed();select('frame:'+first.id);fit();},box);
      box.append(addElement('p','确认只展开下一步，不会自动调用模型。','hint'));
    }
    if(kind==='role'&&r){button('返回创作起点',()=>select('story'),box,true);field('角色名称',r.name,v=>r.name=v.slice(0,80),box);field('固定外貌 / 发型 / 服装',r.description,v=>r.description=v.slice(0,600),box,true);if(r.asset_id){const img=addElement('img');img.src=assetURL(r.asset_id);img.alt=r.name;box.append(img);}const upload=addElement('input');upload.type='file';upload.accept='image/jpeg,image/png,image/webp';upload.setAttribute('aria-label','上传角色参考图');upload.dataset.mutates='true';upload.onchange=()=>uploadRole(r,upload.files[0]);box.append(upload);const choices=[['','从已有关键帧选择…'],...[...frames.values()].filter(f=>f.status==='success').map(f=>[f.id,'镜头'+f.shot+' · '+f.id.slice(0,8)])];options('采用已有关键帧作角色参考',choices,'',value=>{if(value)importRole(r,value);},box);
      const acts=addElement('div',undefined,'actions');button('用于全部片段',()=>{board.shots.forEach(s=>{if(!s.role_ids.includes(r.id))s.role_ids.push(r.id);});changed();renderInspector();},acts,true);button('删除角色节点',()=>{board.roles=board.roles.filter(x=>x.id!==r.id);board.shots.forEach(s=>s.role_ids=s.role_ids.filter(x=>x!==r.id));selected='story';changed();renderInspector();},acts,true).classList.add('danger-soft');box.append(acts);box.append(addElement('p','参考自动沿用到后续片段，无需重复上传。','hint'));}
    if(s&&['shot','frame','video'].includes(kind)){
      if(board.shots.length>1)options('当前片段',board.shots.map(x=>[String(x.id),x.title||'片段'+x.id]),s.id,v=>select((kind==='video'?'video:':'frame:')+v),box);
      if(kind!=='video')renderChangeEditor(s,box);
      const edit=addElement('details',undefined,'intent-advanced');edit.append(addElement('summary','基础设定与连线（高级）'));box.append(edit);
      field('镜头名称',s.title,v=>s.title=v.slice(0,100),edit);field('画面与动作',s.description,v=>s.description=v.slice(0,1200),edit,true);
      options('运镜',['固定','缓推','跟随','拉远','横移'].map(x=>[x,x]),s.camera,v=>{s.camera=v;changed();renderInspector();},edit);
      edit.append(addElement('label','连接的角色参考'));if(!board.roles.length)edit.append(addElement('p','尚无参考素材，可回到创作起点添加。','hint'));board.roles.forEach(r=>check(r.name+(r.asset_id?'':'（缺参考图）'),s.role_ids.includes(r.id),v=>s.role_ids=v?[...s.role_ids,r.id]:s.role_ids.filter(x=>x!==r.id),edit));
      options('衔接前一镜头',[['','独立镜头'],...board.shots.slice(0,board.shots.indexOf(s)).map(p=>[String(p.id),p.title||'镜头'+p.id])],s.previous||'',v=>{s.previous=v?Number(v):null;changed();renderInspector();},edit);
      if(s.frame_id&&frames.get(s.frame_id)?.status==='success'){const im=addElement('img');im.src=frameURL(s.frame_id);im.alt='选中关键帧';box.append(im);const approve=button(s.confirmed_frame_id===s.frame_id&&fresh(s,'frame')?'关键帧已确认':'确认此关键帧，继续生成视频',()=>{if(!fresh(s,'frame')){message('输入已修改，请先重新生成关键帧。',true);return;}s.confirmed_frame_id=s.frame_id;changed();select('video:'+s.id);fit();},box,true);approve.dataset.action='确认关键帧';box.append(addElement('p',fresh(s,'frame')?'先检查人物、动作和构图，再生成视频。':'输入已改动，先生成新的关键帧。','hint'));}
      options('视频输入方式',[['first_frame','首帧驱动（角色经关键帧传入）'],['reference','多参考视频（需额外权限）']],s.video_mode||'first_frame',v=>{s.video_mode=v;changed();renderInspector();},edit);
      const acts=addElement('div',undefined,'actions');if(kind!=='video')button('生成关键帧',()=>generate(s,'frame'),acts);else{button('生成镜头视频',()=>generate(s,'video'),acts);button('返回修改画面',()=>select('frame:'+s.id),acts,true);}box.append(acts);
      const job=jobs.get(s.video_id);if(kind==='video'&&job?.status==='success'){button('下载这一段 MP4',()=>download(videoURL(job.id),'shot-'+s.id+'.mp4'),box,true);if(canMerge())button('合并成片',mergeFilm,box);const v=addElement('video');v.controls=true;v.playsInline=true;v.src=videoURL(job.id);v.setAttribute('aria-label','镜头预览');box.append(v);}else if(job?.error)box.append(addElement('p',job.error,'error-message'));
      if(job&&['query_error','download_failed'].includes(job.status))button('继续查询原任务',()=>resume(job,s),box,true);
      const versions=[['','尚未选择视频'],...[...jobs.values()].filter(j=>j.shot===s.id&&j.status==='success').sort((a,b)=>b.created_at-a.created_at).map(j=>[j.id,j.id.slice(0,8)+' · '+(j.references?.length?'含角色参考':'历史片段')])];options('采用已有视频版本',versions,s.video_id||'',v=>{s.video_id=v||null;s.video_signature=v?'adopted:'+signature(s,'video'):'';changed();renderInspector();},edit);
      check('加入成片',s.included,v=>s.included=v,edit);
      const order=addElement('div',undefined,'actions');button('前移',()=>move(s,-1),order,true);button('后移',()=>move(s,1),order,true);button('删除分镜',()=>{board.shots=board.shots.filter(x=>x.id!==s.id);board.shots.forEach(x=>{if(x.previous===s.id)x.previous=null;});selected='merge';changed();renderInspector();},order,true).classList.add('danger-soft');edit.append(order);
      box.append(addElement('p',!fresh(s,'video')?'输入已改变。已有视频可播放，重新生成或明确采用历史版本后再合并。':!s.video_signature?'当前历史视频未绑定共用角色参考，合并不会修正人物差异。':'连线已记录到生成任务中。','hint'));
    }
    if(kind==='merge'){options('查看片段',[['','选择片段…'],...board.shots.map(x=>[String(x.id),x.title||'片段'+x.id])],'',v=>{if(v)select('video:'+v);},box);box.append(addElement('p','将下方勾选镜头按顺序合并成一条无声MP4。已有片段无需再次调用模型。','hint'));const merge=button('合并成片',mergeFilm,box);merge.disabled=busy>0||!canMerge();if(film){box.append(addElement('p',(statuses[film.status]||film.status)+(film.duration?' · '+film.duration+'秒':'')+(filmCurrent()?'':' · 顺序改变后需重新合并'),'hint'));if(film.status==='success'){const v=addElement('video');v.controls=true;v.src='/api/demo/wan/merges/'+film.id+'/video';v.setAttribute('aria-label','成片预览');box.append(v);button(filmCurrent()?'下载成片 MP4':'下载上一版成片',()=>download('/api/demo/wan/merges/'+film.id+'/video','story-film.mp4'),box,true);}if(film.error)box.append(addElement('p',film.error,'error-message'));}if(!canMerge())box.append(addElement('p','至少勾选两个已完成镜头；有输入变更的镜头需重新生成或明确采用历史版本。','hint'));}
    controls();
  }
  function renderTimeline(){const box=$('graphTimeline');box.replaceChildren();board.shots.forEach((s,i)=>{const item=addElement('div',undefined,'timeline-clip'+(!s.included?' off':''));const input=addElement('input');input.type='checkbox';input.checked=s.included;input.disabled=busy>0;input.setAttribute('aria-label','成片包含镜头'+s.id);input.onchange=()=>{s.included=input.checked;changed();renderInspector();};item.append(input,addElement('span',String(i+1).padStart(2,'0'),'order'),addElement('span',s.title||'镜头'+s.id),addElement('span',resultState(s,'video')));item.onclick=e=>{if(e.target!==input)select('video:'+s.id);};box.append(item);});$('graphTimelineHint').textContent=board.shots.filter(s=>s.included).length+' 个片段 · 在片段设置中前移 / 后移调整顺序';}
  function render(){if(!board)return;renderNodes();renderTimeline();controls();
    const latest=[...jobs.values()].sort((a,b)=>b.created_at-a.created_at)[0];const denied=latest?.error?.includes('AccessDenied.Unpurchased');
    $('graphServiceNotice').hidden=!denied;$('graphServiceNotice').textContent=denied?'视频平台最近返回403：模型调用权限未通过。可继续编辑、生成关键帧和合并已有视频；新视频需平台恢复权限后重试。':'';
  }
  function move(s,delta){const i=board.shots.indexOf(s),j=i+delta;if(j<0||j>=board.shots.length)return;[board.shots[i],board.shots[j]]=[board.shots[j],board.shots[i]];board.shots.forEach((x,k)=>{if(x.previous&&!board.shots.slice(0,k).some(p=>p.id===x.previous))x.previous=null;});board.positions={};changed();renderInspector();message('成片顺序已更新，不再有效的反向衔接已断开。');}
  function queue(j,kind){Studio.updateJob({id:(kind==='frame'?'wan-frame:':kind==='merge'?'wan-merge:':'wan:')+j.id,type:'video',real:true,name:kind==='merge'?'合并成片':(kind==='frame'?'关键帧':'视频')+' · 镜头'+j.shot,status:statuses[j.status]||j.status,progress:j.status==='success'?100:null});}
  function syncAsset(f){if(f.status==='success')Studio.addAssets([{id:'wan-frame:'+f.id,name:'镜头'+f.shot+' · 关键帧',url:frameURL(f.id),kind:'real-keyframe'}]);}
  async function waitTask(id,kind){const base=kind==='frame'?'keyframes':kind==='merge'?'merges':'jobs';for(;;){const data=await api('/api/demo/wan/'+base+'/'+id);if(kind==='frame'){frames.set(id,data);syncAsset(data);}else if(kind==='video')jobs.set(id,data);else film=data;queue(data,kind);render();if(!active.has(data.status))return data;await new Promise(resolve=>setTimeout(resolve,2000));}}
  async function uploadRole(r,file){if(!file)return;busy++;controls();try{const form=new FormData();form.append('image',file);const a=await api('/api/demo/wan/assets',{method:'POST',body:form});r.asset_id=a.id;changed();message('参考已保存，将自动用于已关联的片段。');}catch(e){message(e.message,true);}finally{busy--;renderInspector();}}
  async function importRole(r,id){busy++;controls();try{const a=await api('/api/demo/wan/assets/import',post({frame_id:id,name:r.name}));r.asset_id=a.id;changed();message('已采用该关键帧作为固定角色参考。');}catch(e){message(e.message,true);}finally{busy--;renderInspector();}}
  async function asData(url){const r=await fetch(url);if(!r.ok)throw new Error('关键帧读取失败');const b=await r.blob();return new Promise((resolve,reject)=>{const f=new FileReader();f.onload=()=>resolve(f.result);f.onerror=()=>reject(new Error('图片读取失败'));f.readAsDataURL(b);});}
  function inputs(s){const roles=board.roles.filter(r=>s.role_ids.includes(r.id));if(roles.some(r=>!r.asset_id))throw new Error('有角色尚未上传参考图，请先补齐参考。');const prev=shot(s.previous);let previous_video_id=null,previous_frame_id=null;
    if(prev){if(prev.video_signature&&jobs.get(prev.video_id)?.status==='success'&&fresh(prev,'video'))previous_video_id=prev.video_id;else if(frames.get(prev.frame_id)?.status==='success'&&fresh(prev,'frame'))previous_frame_id=prev.frame_id;else throw new Error('请先完成所连接前一镜头的视频或关键帧。');}
    return {project:Studio.project(),shot:s.id,story_context:board.story,workflow_signature:signature(s),references:roles.map(r=>({asset_id:r.asset_id,name:r.name})),video_mode:s.video_mode||'first_frame',previous_video_id,previous_frame_id,prompt:Intent.prompt(board,s)};
  }
  async function generate(s,kind){if(busy||conflict||!configured)return;if(stepCount()<2){message('请先确认创作起点。',true);return;}if(drafts.get(s.id)?.trim()){message('请先应用或清空本次修改，再生成。',true);return;}if(!s.description.trim()){message('请填写当前分镜的画面与动作。',true);return;}
    busy++;controls();try{const payload=inputs(s);if(payload.prompt.length>9800)throw new Error('累计要求过长，请撤销不再需要的修改，或精简基础设定');if(kind==='frame'&&s.changes?.length&&frames.get(s.frame_id)?.status==='success'){payload.image=await asData(frameURL(s.frame_id));payload.prompt+='最后一张补充参考是当前镜头的已有画面，只修改指定部分，其余构图与人物保持。';}if(kind==='video'){if(s.confirmed_frame_id!==s.frame_id)throw new Error('请先确认关键帧符合预期，再生成视频');if(frames.get(s.frame_id)?.status!=='success')throw new Error('请先生成关键帧');if(!fresh(s,'frame')||(payload.references.length&&!s.frame_signature))throw new Error('角色或场景输入已改变，请先重新生成关键帧');payload.image=await asData(frameURL(s.frame_id));payload.workflow_signature=signature(s,'video');}
      payload.request_id=crypto.randomUUID();const data=await api('/api/demo/wan/'+(kind==='frame'?'keyframes':'jobs'),post(payload));s[kind+'_id']=data.id;if(kind==='frame')s.confirmed_frame_id=null;s[kind+'_signature']=payload.workflow_signature;(kind==='frame'?frames:jobs).set(data.id,data);changed();message('正在生成'+(kind==='frame'?'关键帧':'视频')+'，共用参考与衔接关系已提交。');const result=await waitTask(data.id,kind);message(result.status==='success'?'生成完成。请检查人物和镜头衔接后再合并。':result.error||'生成未完成',result.status!=='success');
    }catch(e){message(e.message,true);}finally{busy--;changed();renderInspector();}}
  async function resume(j,s){if(busy)return;busy++;controls();try{await api('/api/demo/wan/jobs/'+j.id+'/resume',{method:'POST'});const r=await waitTask(j.id,'video');message(r.status==='success'?'原任务已恢复。':r.error||'查询未完成',r.status!=='success');}catch(e){message(e.message,true);}finally{busy--;renderInspector();}}
  async function mergeFilm(){if(busy||!canMerge())return;busy++;selected='merge';controls();try{film=await api('/api/demo/wan/merges',post({request_id:crypto.randomUUID(),ids:outputIds(),project:Studio.project()}));board.merge_id=film.id;changed();renderInspector();message('正在本地合并，不重新生成镜头。');const r=await waitTask(film.id,'merge');message(r.status==='success'?'成片已合并，可直接播放和导出一条MP4。':r.error,r.status!=='success');}catch(e){message(e.message,true);}finally{busy--;renderInspector();}}
  async function download(url,name,options){try{const r=await fetch(url,options);if(!r.ok)throw new Error('导出失败，请检查任务状态');Studio.downloadBlob(await r.blob(),name);message('已导出 '+name);}catch(e){message(e.message,true);}}
  $('graphMerge').onclick=mergeFilm;$('graphFilmExport').onclick=()=>download('/api/demo/wan/merges/'+film.id+'/video','story-film.mp4');$('realSingleExport').onclick=()=>download(videoURL(currentShot().video_id),'shot-'+currentShot().id+'.mp4');$('realAllExport').onclick=()=>download('/api/demo/wan/export','story-clips.zip',post({ids:board.shots.filter(s=>jobs.get(s.video_id)?.status==='success').map(s=>s.video_id)}));
  $('graphAddShot').onclick=()=>{const id=Math.max(0,...board.shots.map(s=>s.id),...[...jobs.values()].map(j=>j.shot))+1;board.shots.push(Intent.newShot(board,id));selected='frame:'+id;changed();renderInspector();fit();};
  $('graphAddRole').onclick=()=>{const r={id:crypto.randomUUID(),name:'角色'+(board.roles.length+1),description:'',asset_id:null};board.roles.push(r);board.shots.forEach(s=>s.role_ids.push(r.id));selected='role:'+r.id;changed();renderInspector();fit();};
  $('graphArrange').onclick=()=>{board.positions={};changed();fit();};$('graphFit').onclick=fit;
  function zoomBy(factor){const v=$('graphViewport'),cx=v.clientWidth/2,cy=v.clientHeight/2,newZoom=Math.max(.25,Math.min(1.5,zoom*factor));pan={x:cx-(cx-pan.x)*newZoom/zoom,y:cy-(cy-pan.y)*newZoom/zoom};zoom=newZoom;transform();}
  $('graphZoomIn').onclick=()=>zoomBy(1.2);$('graphZoomOut').onclick=()=>zoomBy(1/1.2);
  $('graphViewport').onpointerdown=e=>{if(e.button!==0||e.target.closest('.graph-node')||e.target.closest('.edge'))return;const start={x:e.clientX,y:e.clientY,pan:{...pan}},view=$('graphViewport');view.setPointerCapture(e.pointerId);view.onpointermove=ev=>{pan={x:start.pan.x+ev.clientX-start.x,y:start.pan.y+ev.clientY-start.y};transform();};view.onpointerup=()=>{view.onpointermove=null;view.onpointerup=null;};};
  $('graphViewport').onkeydown=e=>{if(e.key==='Escape'){connection=null;renderNodes();message('已取消连接。');}};
  window.addEventListener('studio:viewjob',e=>{if(e.detail.type!=='video')return;mode(e.detail.real?'real':'prototype');if(e.detail.id.startsWith('wan:')){const s=board.shots.find(s=>s.video_id===e.detail.id.slice(4));if(s)select('video:'+s.id);}if(e.detail.id.startsWith('wan-merge:'))select('merge');});
  async function initialize(){try{const [c,h,f,b]=await Promise.all([api('/api/demo/wan/config'),api('/api/demo/wan/jobs'),api('/api/demo/wan/keyframes'),api('/api/demo/wan/board')]);configured=c.configured;h.jobs.forEach(j=>jobs.set(j.id,j));f.frames.forEach(x=>frames.set(x.id,x));board=b.board;
      if(!board){let legacy;try{legacy=JSON.parse(Studio.read('studio.realVideo')||'null');}catch(_){}const ids=[...new Set(h.jobs.map(j=>j.shot).filter(n=>n<100000))].sort((a,b)=>a-b);if(!ids.length)ids.push(1);board={revision:0,story:'',roles:[],positions:{},merge_id:null,shots:ids.slice(0,12).map(id=>{const old=legacy?.shots?.find(s=>s.id===id),j=h.jobs.find(j=>j.shot===id&&j.status==='success'),fr=f.frames.find(f=>f.shot===id&&f.status==='success');return {id,title:'镜头'+id,description:old?.description||j?.prompt.split('。运镜：')[0]||'',camera:old?.camera||'固定',role_ids:[],previous:null,frame_id:fr?.id||null,frame_signature:'',video_id:j?.id||null,video_signature:'',included:true};})};dirty=true;await save();}
      if(!board.shots.length){board.shots.push(Intent.newShot(board,Math.max(0,...h.jobs.map(j=>j.shot))+1));dirty=true;await save();}
      if(board.merge_id){try{film=await api('/api/demo/wan/merges/'+board.merge_id);}catch(_){}}
      mode('real');render();renderInspector();fit();h.jobs.forEach(j=>queue(j,'video'));f.frames.forEach(syncAsset);message('从创作起点开始，确认画面后再生成视频。已有片段和成片已保留。');
      const pending=board.shots.flatMap(s=>[['frame',frames.get(s.frame_id)],['video',jobs.get(s.video_id)]]).filter(([k,j])=>j&&active.has(j.status));if(film&&active.has(film.status))pending.push(['merge',film]);
      for(const [kind,j] of pending){busy++;controls();try{await waitTask(j.id,kind);}catch(e){message(e.message,true);}finally{busy--;renderInspector();}}
    }catch(e){message('画布加载失败：'+e.message+'。刷新后可重试。',true);}}
  window.addEventListener('resize',()=>{if(board)transform();});
  initialize();
})();
