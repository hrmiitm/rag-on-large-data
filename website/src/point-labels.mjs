// Numeric labels keep their true data anchors. Only the text boxes move.
export function labelXRange(points,log=false) {
 const values=points.filter(p=>Number.isFinite(p.x)&&(!log||p.x>0)).map(p=>log?Math.log10(p.x):p.x);
 if(!values.length)return undefined;
 const lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||Math.max(Math.abs(lo)*.1,.1);
 return [lo-span*.12,hi+span*.12];
}
const overlap=(a,b,gap=3)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left)+gap)*Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)+gap);
export function placePointLabels(points,{width,height,xRange,yRange,log=false}) {
 const visible=points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&(!log||p.x>0)).map(p=>{
  const x=log?Math.log10(p.x):p.x;
  return {...p,axisX:x,px:(x-xRange[0])/(xRange[1]-xRange[0])*width,py:(yRange[1]-p.y)/(yRange[1]-yRange[0])*height};
 }).filter(p=>p.px>=0&&p.px<=width&&p.py>=0&&p.py<=height);
 const boxes=[],result=[];
 // Place crowded anchors first, with deterministic ties independent of trace order.
 const density=p=>visible.filter(q=>Math.hypot(p.px-q.px,p.py-q.py)<110).length;
 for(const p of [...visible].sort((a,b)=>density(b)-density(a)||String(a.key).localeCompare(String(b.key)))) {
  const lines=p.text.split('<br>'),w=Math.min(width-4,Math.max(...lines.map(s=>s.length))*6+10),h=lines.length*14+6;
  const candidates=[];
  for(const gap of [6,20,38,62,92,130])for(const [dx,dy]of [[1,-1],[1,1],[-1,-1],[-1,1],[0,-1],[0,1],[1,0],[-1,0]]) {
   candidates.push([p.px+dx*(18+gap+w/2),p.py+dy*(18+gap+h/2)]);
  }
  // A dense cluster can need more room than the immediate marker perimeter.
  for(let y=h/2+2;y<height-h/2;y+=18)for(let x=w/2+2;x<width-w/2;x+=24)candidates.push([x,y]);
  let best;
  for(const [cx,cy]of candidates) {
   const box={left:cx-w/2,right:cx+w/2,top:cy-h/2,bottom:cy+h/2};
   if(box.left<2||box.right>width-2||box.top<2||box.bottom>height-2)continue;
   const collisions=boxes.reduce((s,b)=>s+overlap(box,b),0)+visible.reduce((s,q)=>s+overlap(box,{left:q.px-18,right:q.px+18,top:q.py-18,bottom:q.py+18}),0);
   const distance=Math.hypot(cx-p.px,cy-p.py),score=collisions*10000+distance;
   if(!best||score<best.score)best={score,box,cx,cy};
  }
  if(!best)continue;
  boxes.push(best.box);
  result.push({key:p.key,box:best.box,anchor:{x:p.px,y:p.py},annotation:{
   x:p.axisX,y:p.y,xref:'x',yref:'y',text:p.text,showarrow:true,arrowhead:0,arrowwidth:.6,
   ax:best.cx-p.px,ay:best.cy-p.py,axref:'pixel',ayref:'pixel',standoff:17,
   xanchor:'center',yanchor:'middle',align:'center',borderpad:2,captureevents:false,
  }});
 }
 return result;
}
