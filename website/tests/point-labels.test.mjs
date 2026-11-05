import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';
import {labelXRange,placePointLabels} from '../src/point-labels.mjs';import {groupRows} from '../src/data.mjs';
const base=new URL('../public/data/',import.meta.url),manifest=JSON.parse(fs.readFileSync(new URL('manifest.json',base))),{rows}=JSON.parse(fs.readFileSync(new URL(manifest.data,base)));
const points=groupRows(rows).map(g=>({key:g.key,x:g.cost,y:g.scores.answer_correctness*100,text:`${(g.scores.answer_correctness*100).toFixed(1)}% · $${g.cost.toFixed(2)}<br>${Math.round(g.latency*1000).toLocaleString('en-US')} ms`}));
const overlap=(a,b)=>Math.min(a.right,b.right)>Math.max(a.left,b.left)&&Math.min(a.bottom,b.bottom)>Math.max(a.top,b.top);
test('live clustered labels stay within the plot without covering labels or circles at multiple widths',()=>{
 for(const log of [true,false])for(const width of [280,420,800,1050]){
  const xRange=labelXRange(points,log),yRange=[40,105],height=402;
  const placed=placePointLabels(points,{width,height,xRange,yRange,log});assert.equal(placed.length,points.length);
  for(const p of placed){assert.ok(p.box.left>=0&&p.box.right<=width&&p.box.top>=0&&p.box.bottom<=height);
   for(const q of placed){if(q!==p)assert.ok(!overlap(p.box,q.box),`labels overlap at ${width}, log=${log}`);
    assert.ok(!overlap(p.box,{left:q.anchor.x-17,right:q.anchor.x+17,top:q.anchor.y-17,bottom:q.anchor.y+17}),`label covers a marker at ${width}`);
   }
  }
 }
});
test('log annotations retain the correct anchor and ignore invalid/zero costs',()=>{
 const input=[{key:'valid',x:.01,y:80,text:'80.0% · $0.01<br>12,345 ms'},{key:'zero',x:0,y:80,text:'zero'},{key:'missing',x:null,y:80,text:'missing'}];
 const xRange=labelXRange(input,true);const [p]=placePointLabels(input,{width:500,height:400,xRange,yRange:[0,105],log:true});
 assert.equal(p.annotation.x,-2);assert.equal(p.annotation.y,80);assert.equal(p.annotation.axref,'pixel');assert.equal(p.annotation.showarrow,true);assert.equal(p.annotation.text,input[0].text);
 assert.equal(labelXRange([],true),undefined);
});
test('zoom ranges show labels only for visible points and recompute text offsets',()=>{
 const xRange=labelXRange(points,true),all=placePointLabels(points,{width:800,height:402,xRange,yRange:[40,105],log:true});
 const zoomed=placePointLabels(points,{width:420,height:402,xRange:[Math.log10(.025),Math.log10(.05)],yRange:[70,100],log:true});
 assert.ok(zoomed.length<all.length);for(const p of zoomed){assert.equal(p.annotation.x,Math.log10(points.find(q=>q.key===p.key).x));assert.ok(p.box.right<=420);}
});
