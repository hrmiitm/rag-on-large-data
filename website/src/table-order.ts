/** Missing values stay last in either direction; numeric values sort numerically. */
export function compareValues(a:unknown,b:unknown,desc=false):number {
  const missing=(v:unknown)=>v===null||v===undefined||v===''||(typeof v==='number'&&!Number.isFinite(v));
  if(missing(a))return missing(b)?0:1;
  if(missing(b))return -1;
  const result=typeof a==='number'&&typeof b==='number'?a-b:
    typeof a==='number'?-1:typeof b==='number'?1:String(a).localeCompare(String(b),undefined,{numeric:true});
  return desc?-result:result;
}
