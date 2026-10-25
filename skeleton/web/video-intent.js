/* Pure workflow rules shared by the editor and its regression checks. */
(function(root){
  const rolesFor=(board,shot)=>board.roles.filter(r=>shot.role_ids.includes(r.id));
  function affected(board,id){
    const ids=new Set([id]);
    for(const s of board.shots)if(ids.has(s.previous))ids.add(s.id);
    return board.shots.filter(s=>ids.has(s.id));
  }
  function newShot(board,id){
    const previous=board.shots.at(-1);
    return {id,title:'新分镜',description:'',camera:previous?.camera||'固定',
      role_ids:previous?[...previous.role_ids]:board.roles.map(r=>r.id),previous:previous?.id||null,
      changes:[],confirmed_frame_id:null,frame_id:null,frame_signature:'',video_id:null,video_signature:'',included:true};
  }
  function prompt(board,shot){
    const roles=rolesFor(board,shot),changes=shot.changes||[];
    return '固定背景（只用于人物与环境，不在本镜头演完整个故事）：'+board.story+
      '\n固定角色：'+roles.map(r=>r.name+'：'+r.description).join('；')+
      '\n原镜头动作：'+shot.description+'。运镜：'+shot.camera+
      (changes.length?'\n本镜头累计修改（按先后顺序；同一动作要求冲突时以后面的修改为准，其余要求继续保留）：\n'+changes.map((c,i)=>(i+1)+'. '+c).join('\n'):'')+
      '\n仅表现本镜头的最终动作；修改要求只调整本镜头，未涉及的人物身份、服装、场景和风格保持原设定。不要提前演后续剧情，不添加未指定动作，单一连续镜头，无字幕。';
  }
  function visibleSteps(board,frames,jobs,confirmed,validFrame){
    const hasFrame=board.shots.some(s=>s.frame_id&&frames.has(s.frame_id));
    const hasVideo=board.shots.some(s=>s.video_id&&jobs.has(s.video_id));
    const ready=board.shots.some(s=>s.frame_id&&s.confirmed_frame_id===s.frame_id&&frames.get(s.frame_id)?.status==='success'&&validFrame(s));
    return hasVideo||ready?3:confirmed||hasFrame?2:1;
  }
  const api={rolesFor,affected,newShot,prompt,visibleSteps};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.VideoIntent=api;
})(globalThis);
