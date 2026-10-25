/* Pure duration allocation, shared by the UI and its contract tests. */
(function(root){
  function split(total, count=3){
    if(!Number.isInteger(count)||count<1||!Number.isInteger(total)||total<count*2||total>count*30)
      throw new RangeError(`请输入 ${count*2}–${count*30} 之间的整数秒数`);
    const base=Math.floor(total/count), remainder=total%count;
    return Array.from({length:count},(_,i)=>base+(i<remainder?1:0));
  }
  const api={presets:[15,30,60],split};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.AdDuration=api;
})(globalThis);
