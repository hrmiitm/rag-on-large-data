import {useEffect,useRef,useState} from 'react';
// The basic bundle includes the scatter and bar traces used here. Heatmaps are accessible HTML.
let plotly:Promise<any>|undefined;
const load=()=>plotly??=import('plotly.js-basic-dist-min').then(m=>m.default??m);
export default function Plot({data,xTitle,yTitle='Mean answer correctness (%)',dark=false,log=false,onClick,onHover,onLeave,height=440,revision='chart',empty}:{data:any[];xTitle:string;yTitle?:string;dark?:boolean;log?:boolean;onClick?:(p:any)=>void;onHover?:(p:any)=>void;onLeave?:()=>void;height?:number;revision?:string;empty?:string}){
 const el=useRef<HTMLDivElement>(null),handlers=useRef({onClick,onHover,onLeave}),[error,setError]=useState('');handlers.current={onClick,onHover,onLeave};
 useEffect(()=>{let disposed=false;const current=el.current;let resize:ResizeObserver|undefined;
  if(!current)return;
  load().then(async P=>{if(disposed)return;await P.react(current,data,{height,margin:{l:76,r:36,t:28,b:80},paper_bgcolor:'transparent',plot_bgcolor:'transparent',font:{family:'system-ui, -apple-system, Segoe UI, sans-serif',color:dark?'#bbc6c1':'#62716b',size:14},xaxis:{title:{text:xTitle,font:{size:14}},type:log?'log':undefined,gridcolor:dark?'#38483d':'#e2e6df',zeroline:false,automargin:true},yaxis:{title:{text:yTitle,font:{size:14}},gridcolor:dark?'#38483d':'#e2e6df',zeroline:false,range:yTitle.includes('(%)')?[0,105]:undefined,automargin:true},barmode:'group',showlegend:false,hovermode:'closest',hoverlabel:{bgcolor:dark?'#20372c':'#fff',font:{color:dark?'#eff5f1':'#24362e',size:15}},uirevision:revision,dragmode:'zoom',annotations:empty?[{text:empty,xref:'paper',yref:'paper',x:0.5,y:0.52,showarrow:false,font:{size:13,color:dark?'#adbeb4':'#64766c'}}]:[]},{responsive:true,displaylogo:false,scrollZoom:false,toImageButtonOptions:{format:'png',filename:'sec-rag-benchmark',scale:2},modeBarButtonsToRemove:['lasso2d','select2d']});if(disposed)return;
   const node=current as any;node.removeAllListeners?.('plotly_click');node.removeAllListeners?.('plotly_hover');node.removeAllListeners?.('plotly_unhover');node.on('plotly_click',(e:any)=>handlers.current.onClick?.(e.points[0]));node.on('plotly_hover',(e:any)=>handlers.current.onHover?.(e.points[0]));node.on('plotly_unhover',()=>handlers.current.onLeave?.());
   resize=new ResizeObserver(()=>P.Plots.resize(current));resize.observe(current);
  }).catch(e=>setError(String(e)));
  return()=>{disposed=true;resize?.disconnect();};
 },[data,dark,height,xTitle,yTitle,log,revision,empty]);
 useEffect(()=>{const current=el.current;return()=>{if(current)load().then(P=>P.purge(current));};},[Boolean(empty)]);
 if(empty)return <div className="chart-empty" role="status">{empty}</div>;
 return <div className="plot-wrap"><div ref={el} role="img" aria-label={`${yTitle} by ${xTitle}. Use the adjacent table for exact values.`} style={{minHeight:height}}/>{error&&<p role="alert">Chart unavailable: {error}. Exact values remain in the tables.</p>}<div className="plot-export"><button onClick={()=>el.current&&load().then(P=>P.downloadImage(el.current,{format:'png',filename:'sec-rag-benchmark',width:1000,height,scale:2}))}>PNG ↓</button><button onClick={()=>el.current&&load().then(P=>P.downloadImage(el.current,{format:'svg',filename:'sec-rag-benchmark',width:1000,height}))}>SVG ↓</button></div></div>;
}
