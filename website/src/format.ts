import {mean,numeric} from './data.mjs';
export const num=(v:unknown,d=1)=>numeric(v)===null?'N/A':Number(v).toLocaleString('en-US',{maximumFractionDigits:d});
export const money=(v:unknown)=>numeric(v)===null?'N/A':`$${Number(v).toFixed(Number(v)<1?4:2)}`;
export const percent=(v:unknown)=>numeric(v)===null?'Not Evaluated':`${(Number(v)*100).toFixed(1)}%`;
export const seconds=(v:unknown)=>numeric(v)===null?'N/A':`${Number(v).toFixed(2)} s`;
export const shortModel=(s:string)=>s.split('/').at(-1)??s;
export const color=(s:string)=>{let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))|0;return ['#17785d','#4e73c2','#b7722f','#a65f9e','#208697','#a85659','#79712f','#6561ad'][Math.abs(h)%8];};
export const metricMean=(rows:{metrics:Record<string,any>}[],key:string)=>mean(rows.map(r=>numeric(r.metrics[key])));
export function download(text:string,name:string,type='text/csv') {const u=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
