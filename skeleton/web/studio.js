/* Shared project state lives outside both panels. Switching only changes visibility. */
(() => {
  const el = id => document.getElementById(id);
  const assets = new Map();
  const jobs = new Map();
  let tab = 'image';
  let videoState = null;
  function notice(message) { el('shellNotice').textContent = message; }
  function store(key, value) { try { localStorage.setItem(key, value); } catch (_) { notice('浏览器存储不可用，本次会话仍可继续使用。'); } }
  function read(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  el('projectName').value = read('studio.projectName') || '我的创作项目';
  el('projectName').addEventListener('input', () => store('studio.projectName', el('projectName').value));
  function switchTab(next) {
    tab = next;
    document.body.classList.toggle('ad-active',next==='video');
    for (const type of ['image','video']) {
      el(type + 'Panel').hidden = type !== next;
      el(type + 'Tab').setAttribute('aria-selected', String(type === next));
      el(type + 'Tab').tabIndex = type === next ? 0 : -1;
      el(type + 'Exports').hidden = type !== next;
    }
    el('exportTitle').textContent = next === 'image' ? '图片导出' : '视频导出';
    el('exportHint').textContent = next === 'image' ? '选择成功图片后下载，全部导出附带生成记录。' : '导出广告成片、选中片段或全部视频，旧版记录保留在视频页入口。';
    store('studio.tab', next);
  }
  ['image','video'].forEach(type => {
    el(type + 'Tab').onclick = () => switchTab(type);
    el(type + 'Tab').onkeydown = e => { if (['ArrowLeft','ArrowRight'].includes(e.key)) { e.preventDefault(); const next=type==='image'?'video':'image'; switchTab(next); el(next+'Tab').focus(); } };
  });
  function renderAssets() {
    const box = el('assetLibrary'); box.replaceChildren();
    el('assetCount').textContent = assets.size;
    if (!assets.size) { const p=document.createElement('p'); p.className='empty'; p.textContent='暂无素材。先在图片页上传商品图，或在视频页生成示例关键帧。'; box.append(p); }
    for (const a of assets.values()) {
      const item=document.createElement('div'); item.className='asset-item';
      const img=document.createElement('img'); img.src=a.url; img.alt=a.name;
      const name=document.createElement('span'); name.textContent=a.name; name.title=a.name;
      const type=document.createElement('span'); type.textContent=a.kind==='upload'?'上传参考':a.kind==='image'?'图片结果':a.kind==='real-keyframe'?'模型关键帧':'示例关键帧';
      item.append(img,name,type); box.append(item);
    }
    window.dispatchEvent(new CustomEvent('studio:assets'));
  }
  function addAssets(items) { items.forEach(a=>assets.set(a.id,a)); renderAssets(); }
  function syncUploads(files) {
    for (const [id,a] of assets) if (a.kind==='upload') assets.delete(id);
    addAssets(files.map(f=>({id:'upload:'+f.file.name+':'+f.file.size+':'+f.file.lastModified,name:f.file.name,url:f.dataUrl,kind:'upload'})));
  }
  const labels={generating:'进行中',canceling:'取消中',success:'已完成',partial:'部分成功',failed:'失败',canceled:'已取消',interrupted:'已中断',prototype:'原型就绪'};
  function updateJob(job) {
    jobs.set(job.id,job); el('queueCount').textContent=jobs.size;
    const box=el('taskQueue'); box.replaceChildren();
    for (const j of [...jobs.values()].reverse().slice(0,8)) {
      const row=document.createElement('div'); row.className='queue-row';
      const name=document.createElement('div'); name.className='queue-info'; name.textContent=(j.type==='image'?'图片 · ':j.real?(j.kind==='frame'?'真实关键帧 · ':'真实视频 · '):'视频原型 · ')+j.name;
      const state=document.createElement('span'); state.className='queue-state'; state.textContent=labels[j.status]||j.status;
      const progress=document.createElement('progress'); progress.max=100; if(j.progress==null&&j.real)progress.removeAttribute('value');else progress.value=j.progress||0; progress.setAttribute('aria-label',j.name+'进度');
      const view=document.createElement('button'); view.className='mini'; view.textContent='查看'; view.onclick=()=>{switchTab(j.type);window.dispatchEvent(new CustomEvent('studio:viewjob',{detail:j}));};
      row.append(name,state,progress,view); box.append(row);
    }
  }
  function downloadBlob(blob,name) { const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=name; document.body.append(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),30000); }
  el('projectExport').onclick=()=>downloadBlob(new Blob([JSON.stringify({schema_version:1,project:el('projectName').value||'我的创作项目',exported_at:new Date().toISOString(),active_tab:tab,assets:[...assets.values()].map(({url,...metadata})=>metadata),queue:[...jobs.values()],video_prototype:videoState,ad_canvas:JSON.parse(read('studio.adCanvas.v2')||'null'),video_real:JSON.parse(read('studio.realVideo')||'null'),video_workflow:JSON.parse(read('studio.workflowDraft')||'null'),ad_draft:JSON.parse(read('studio.adDraft')||'null'),note:'项目记录不包含图片二进制；图片与视频文件请用对应导出按钮下载。'},null,2)],{type:'application/json'}),'studio-project.json');
  window.Studio={removeJob:id=>jobs.delete(id),switchTab,syncUploads,addAssets,updateJob,assets:()=>[...assets.values()],notice,read,store,downloadBlob,project:()=>el('projectName').value||'我的创作项目',setVideoState:s=>{videoState=s;}};
  switchTab(read('studio.tab')==='video'?'video':'image');
})();
