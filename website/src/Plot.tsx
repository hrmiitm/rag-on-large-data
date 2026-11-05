import {useEffect,useRef,useState} from 'react';
import {labelXRange,placePointLabels} from './point-labels.mjs';
export type PointLabel={key:string;x:number;y:number;text:string};
// The basic bundle includes the scatter and bar traces used here. Heatmaps are accessible HTML.
let plotly:Promise<any>|undefined;
const load=()=>plotly??=import('plotly.js-basic-dist-min').then(m=>m.default??m);
export default function Plot({data,xTitle,yTitle='Mean answer correctness (%)',dark=false,log=false,onClick,onHover,onLeave,height=440,revision='chart',empty,xFormat,yRange,pointLabels}:{data:any[];xTitle:string;yTitle?:string;dark?:boolean;log?:boolean;onClick?:(p:any)=>void;onHover?:(p:any)=>void;onLeave?:()=>void;height?:number;revision?:string;empty?:string;xFormat?:string;yRange?:[number,number];pointLabels?:PointLabel[]}){
 const el=useRef<HTMLDivElement>(null),handlers=useRef({onClick,onHover,onLeave}),[error,setError]=useState('');handlers.current={onClick,onHover,onLeave};
 useEffect(()=>{let disposed=false;const current=el.current;let resize:ResizeObserver|undefined;
  if(!current)return;
  load().then(async P=>{if(disposed)return;
   const margin={l:68,r:26,t:26,b:72},axisRange=pointLabels?labelXRange(pointLabels,log):undefined;
   const qualityRange=yRange??(yTitle.includes('(%)')?[0,105]:undefined);
   let lastWidth=current.clientWidth;
   const annotations=(xr=axisRange,yr=qualityRange)=>pointLabels&&xr&&yr?placePointLabels(pointLabels,{width:Math.max(40,(current.clientWidth||900)-margin.l-margin.r),height:height-margin.t-margin.b,xRange:xr,yRange:yr,log}).map(p=>({...p.annotation,font:{size:10.5,color:dark?'#eff5f1':'#27372f'},bgcolor:dark?'rgba(24,39,32,.94)':'rgba(255,255,255,.94)',arrowcolor:dark?'#a8bdb1':'#7c8c84'})):[];
   await P.react(current,data,{height,margin,paper_bgcolor:'transparent',plot_bgcolor:'transparent',font:{family:'system-ui, -apple-system, Segoe UI, sans-serif',color:dark?'#bbc6c1':'#62716b',size:14},xaxis:{title:{text:xTitle,font:{size:14}},type:log?'log':undefined,range:axisRange,tickformat:xFormat,gridcolor:dark?'#38483d':'#e2e6df',zeroline:false,automargin:!pointLabels},yaxis:{title:{text:yTitle,font:{size:14}},gridcolor:dark?'#38483d':'#e2e6df',zeroline:false,range:qualityRange,automargin:true},barmode:'group',showlegend:false,hovermode:'closest',hoverlabel:{bgcolor:dark?'#20372c':'#fff',font:{color:dark?'#eff5f1':'#24362e',size:13}},uirevision:revision,dragmode:'zoom',annotations:empty?[{text:empty,xref:'paper',yref:'paper',x:0.5,y:0.52,showarrow:false,font:{size:13,color:dark?'#adbeb4':'#64766c'}}]:annotations()},{responsive:true,displaylogo:false,scrollZoom:false,toImageButtonOptions:{format:'png',filename:'sec-rag-benchmark',scale:2},modeBarButtonsToRemove:['lasso2d','select2d']});if(disposed)return;
   const node=current as any;node.removeAllListeners?.('plotly_click');node.removeAllListeners?.('plotly_hover');node.removeAllListeners?.('plotly_unhover');node.on('plotly_click',(e:any)=>handlers.current.onClick?.(e.points[0]));node.on('plotly_hover',(e:any)=>handlers.current.onHover?.(e.points[0]));node.on('plotly_unhover',()=>handlers.current.onLeave?.());
   // Plotly preserves user zoom with uirevision. Re-layout labels against the
   // displayed public layout ranges rather than the original full-data range.
   const validRange=(value:any)=>Array.isArray(value)&&value.length===2&&value.every(Number.isFinite);
   const ranges={x:validRange(node.layout?.xaxis?.range)?node.layout.xaxis.range:axisRange,y:validRange(node.layout?.yaxis?.range)?node.layout.yaxis.range:qualityRange};
   if(pointLabels&&JSON.stringify([ranges.x,ranges.y])!==JSON.stringify([axisRange,qualityRange]))await P.relayout(current,{annotations:annotations(ranges.x,ranges.y)});
   node.removeAllListeners?.('plotly_relayout');
   node.on('plotly_relayout',(event:any)=>{
    const changed=['xaxis.range[0]','yaxis.range[0]','xaxis.range','yaxis.range','xaxis.autorange','yaxis.autorange'].some(k=>k in event);
    if(!pointLabels||!changed)return;
    const nextRange=(axis:string,previous:any,fallback:any)=>validRange(event[`${axis}.range`])?event[`${axis}.range`]:event[`${axis}.range[0]`]!==undefined?[event[`${axis}.range[0]`],event[`${axis}.range[1]`]]:event[`${axis}.autorange`]?(validRange(node.layout?.[axis]?.range)?node.layout[axis].range:fallback):previous;
    ranges.x=nextRange('xaxis',ranges.x,axisRange);ranges.y=nextRange('yaxis',ranges.y,qualityRange);
    P.relayout(current,{annotations:annotations(ranges.x,ranges.y)});
   });
   resize=new ResizeObserver(()=>{if(disposed||current.clientWidth===lastWidth)return;lastWidth=current.clientWidth;
    Promise.resolve(P.Plots.resize(current)).then(()=>{if(!disposed&&pointLabels)P.relayout(current,{annotations:annotations(ranges.x,ranges.y)});}).catch(e=>setError(String(e)));
   });resize.observe(current);
  }).catch(e=>setError(String(e)));
  return()=>{disposed=true;resize?.disconnect();};
 },[data,dark,height,xTitle,yTitle,log,revision,empty,xFormat,yRange,pointLabels]);
 useEffect(()=>{const current=el.current;return()=>{if(current)load().then(P=>P.purge(current));};},[Boolean(empty)]);
 if(empty)return <div className="chart-empty" role="status">{empty}</div>;
 return <div className="plot-wrap"><div ref={el} role="img" aria-label={`${yTitle} by ${xTitle}. Use the adjacent table for exact values.`} style={{minHeight:height}}/>{error&&<p role="alert">Chart unavailable: {error}. Exact values remain in the tables.</p>}<div className="plot-export"><button onClick={()=>el.current&&load().then(P=>P.downloadImage(el.current,{format:'png',filename:'sec-rag-benchmark',width:1000,height,scale:2}))}>PNG ↓</button><button onClick={()=>el.current&&load().then(P=>P.downloadImage(el.current,{format:'svg',filename:'sec-rag-benchmark',width:1000,height}))}>SVG ↓</button></div></div>;
}
