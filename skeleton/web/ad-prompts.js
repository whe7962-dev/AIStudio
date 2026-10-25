/* Preview-only ad planning. Never calls image/video generation endpoints. */
(() => {
  const $=id=>document.getElementById(id);
  const fields={product:'adProduct',requirement:'adRequirement',facts:'adFacts',audience:'adAudience',style:'adStyle',template:'adTemplate'};
  let prepared=null, fingerprint='', loading=false;
  const read=()=>Object.fromEntries(Object.entries(fields).map(([key,id])=>[key,$(id).value]));
  function status(text){$('adStatus').textContent=text;}
  function persist(reviewed=false){Studio.store('studio.adDraft',JSON.stringify({brief:read(),prepared,fingerprint,edited_prompt:$('adPreview').value,reviewed}));}
  function check(){const current=!!prepared&&JSON.stringify(read())===fingerprint;$('adConfirm').disabled=loading||!current||!$('adPreview').value.trim();return current;}
  function show(result){
    $('adPreview').value=result.prompt;$('adPreviewSection').hidden=false;
    $('adPending').replaceChildren(...result.pending_checks.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
  }
  $('adForm').onsubmit=async event=>{
    event.preventDefault();if(loading)return;loading=true;$('adPrepare').disabled=true;check();status('正在按模板整理需求…');
    const brief=read(),sent=JSON.stringify(brief);
    try{
      const response=await fetch('/api/demo/ad/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:sent});
      if(!response.ok)throw new Error(response.status===422?'请检查商品名称、需求及字段长度。':'整理失败，请稍后重试。');
      prepared=await response.json();fingerprint=sent;show(prepared);persist();
      status(JSON.stringify(read())===sent?'方案草稿已整理，请核对卖点和场景。尚未提交生成。':'整理期间输入已改变，请重新整理。');
    }catch(error){status(error.message);}finally{loading=false;$('adPrepare').disabled=false;check();}
  };
  for(const id of Object.values(fields))$(id).addEventListener('input',()=>{check();persist();status('需求已修改，请整理后重新确认。');});
  $('adPreview').oninput=()=>{check();persist();status('方案已编辑，确认后保存。');};
  $('adConfirm').onclick=()=>{if(!check())return;persist(true);status('确认稿已保存在当前浏览器，可随项目记录导出。尚未替换已有镜头或提交生成。');};
  async function init(){
    try{
      const response=await fetch('/api/demo/ad/catalog');if(!response.ok)throw new Error('广告模板加载失败，请刷新重试。');const data=await response.json();
      for(const template of data.templates){const option=new Option(template.name,template.id);option.title=template.use_when;$('adTemplate').add(option);}
      for(const rule of data.rules){const li=document.createElement('li');li.textContent=rule.title+'：'+rule.text;$('adRules').append(li);}
      let saved;try{saved=JSON.parse(Studio.read('studio.adDraft')||'null');}catch(_){}
      if(saved){for(const [key,id]of Object.entries(fields))if(saved.brief?.[key]!==undefined)$(id).value=saved.brief[key];
        if(saved.prepared){prepared=saved.prepared;fingerprint=saved.fingerprint;show(prepared);$('adPreview').value=saved.edited_prompt??prepared.prompt;}
        status(saved.reviewed?'已恢复本浏览器保存的确认稿；生成尚未提交。':'已恢复需求草稿。');
      }else status('第一阶段：整理规则和提示词。确认稿用于后续广告场景与关键帧开发。');
      $('adPrepare').disabled=false;check();
    }catch(error){status(error.message);}
  }
  init();
})();
