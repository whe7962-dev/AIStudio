const assert=require('node:assert/strict');
const {test}=require('node:test');
const {split}=require('../web/ad-studio/duration.js');
test('custom total keeps exact integer seconds within provider limits',()=>{
 for(let total=6;total<=90;total++){
  const parts=split(total);
  assert.equal(parts.reduce((a,b)=>a+b,0),total);
  assert(parts.every(v=>Number.isInteger(v)&&v>=2&&v<=30));
  assert(Math.max(...parts)-Math.min(...parts)<=1);
 }
 assert.deepEqual(split(20),[7,7,6]);
 assert.deepEqual(split(60),[20,20,20]);
});
test('rejects invalid totals rather than rounding or clamping',()=>{
 for(const total of [0,5,91,20.5,NaN,Infinity,'20'])assert.throws(()=>split(total),RangeError);
});
