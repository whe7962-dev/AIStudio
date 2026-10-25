const test=require('node:test');
const assert=require('node:assert/strict');
const intent=require('../web/video-intent.js');
const board={story:'车站，冷灰光线',roles:[{id:'a',name:'女主',description:'灰色外套'}],shots:[
  {id:1,role_ids:['a'],description:'相望',camera:'固定',previous:null},
  {id:2,role_ids:['a'],description:'递信',camera:'缓推',previous:1},
  {id:3,role_ids:[],description:'天空',camera:'固定',previous:null},
  {id:4,role_ids:['a'],description:'离开',camera:'跟随',previous:2}]};
test('新增镜头继承固定角色和前镜头，不编造动作',()=>{
  const s=intent.newShot(board,5);assert.deepEqual(s.role_ids,['a']);assert.equal(s.previous,4);assert.equal(s.description,'');
  s.role_ids.push('b');assert.deepEqual(board.shots[3].role_ids,['a']);
});
test('多轮修改保留基础设定与之前修改，明确后写优先',()=>{
  const s={...board.shots[1],changes:['递信慢一点','不要低头']};const p=intent.prompt(board,s);
  for(const text of ['车站，冷灰光线','女主：灰色外套','原镜头动作：递信','1. 递信慢一点','2. 不要低头','以后面的修改为准'])assert.ok(p.includes(text));
  assert.equal(board.shots[1].description,'递信');assert.ok(!p.includes('天空'));
});
test('影响范围沿衔接传递，独立镜头不被错误标记',()=>{
  assert.deepEqual(intent.affected(board,1).map(s=>s.id),[1,2,4]);
  assert.deepEqual(intent.affected(board,2).map(s=>s.id),[2,4]);
  assert.deepEqual(intent.affected(board,3).map(s=>s.id),[3]);
});
test('从一个起点逐步展开，不因增加片段增加流程节点',()=>{
  const s={id:1},b={shots:[s]},frames=new Map(),jobs=new Map();
  assert.equal(intent.visibleSteps(b,frames,jobs,false,()=>true),1);
  assert.equal(intent.visibleSteps(b,frames,jobs,true,()=>true),2);
  s.frame_id='f';frames.set('f',{status:'success'});
  assert.equal(intent.visibleSteps(b,frames,jobs,false,()=>true),2);
  s.confirmed_frame_id='f';
  assert.equal(intent.visibleSteps(b,frames,jobs,false,()=>false),2);
  assert.equal(intent.visibleSteps(b,frames,jobs,false,()=>true),3);
  b.shots.push({id:2},{id:3});assert.equal(intent.visibleSteps(b,frames,jobs,true,()=>true),3);
});
test('历史视频保留入口，但未完成画面不能首次解锁视频',()=>{
  const s={id:1,frame_id:'f',confirmed_frame_id:'f'},b={shots:[s]},frames=new Map([['f',{status:'generating'}]]),jobs=new Map();
  assert.equal(intent.visibleSteps(b,frames,jobs,true,()=>true),2);
  s.video_id='v';jobs.set('v',{status:'success'});
  assert.equal(intent.visibleSteps(b,frames,jobs,false,()=>true),3);
});
