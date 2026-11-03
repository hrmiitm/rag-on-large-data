import {useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import type {Question} from './types';

/** A portal keeps the preview clear of the table's horizontal-scroll clipping. */
export default function CategoryQuestionPreview({name,count,questions,children}:{name:string;count:number;questions:Question[];children:React.ReactNode}){
  const [position,setPosition]=useState<{left:number;top:number}|null>(null);
  const anchor=useRef<HTMLDivElement>(null),popup=useRef<HTMLDivElement>(null),trigger=useRef<HTMLButtonElement>(null);
  const timer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const id=useId();
  const skipFocus=useRef(false);
  const cancel=()=>{if(timer.current)clearTimeout(timer.current);timer.current=null;};
  const close=()=>{cancel();setPosition(null);};
  const open=()=>{
    cancel();
    const rect=anchor.current?.getBoundingClientRect();if(!rect)return;
    const width=Math.min(400,window.innerWidth-24);
    const beside=rect.right+8+width<=window.innerWidth;
    const left=beside?rect.right+8:Math.max(12,Math.min(rect.left,window.innerWidth-width-12));
    const top=beside?rect.top:rect.bottom+278<window.innerHeight?rect.bottom+8:rect.top-270;
    setPosition({left,top:Math.max(12,Math.min(top,window.innerHeight-270))});
  };
  const later=()=>{cancel();timer.current=setTimeout(()=>setPosition(null),180);};
  useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current);},[]);
  useEffect(()=>{
    if(!position)return;
    const scroll=(e:Event)=>{if(!popup.current?.contains(e.target as Node))setPosition(null);};
    const escape=(e:KeyboardEvent)=>{if(e.key==='Escape'){setPosition(null);if(document.activeElement!==trigger.current){skipFocus.current=true;trigger.current?.focus();}}};
    const outside=(e:PointerEvent)=>{if(!popup.current?.contains(e.target as Node)&&!anchor.current?.contains(e.target as Node))setPosition(null);};
    window.addEventListener('scroll',scroll,true);window.addEventListener('resize',close);window.addEventListener('keydown',escape);window.addEventListener('pointerdown',outside);
    return ()=>{window.removeEventListener('scroll',scroll,true);window.removeEventListener('resize',close);window.removeEventListener('keydown',escape);window.removeEventListener('pointerdown',outside);};
  },[position]);
  return <div ref={anchor} className="category-preview-anchor" onMouseEnter={open} onMouseLeave={later} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node)&&!popup.current?.contains(e.relatedTarget as Node))later();}}>
    {children}
    <button ref={trigger} className="q-count-badge" aria-label={`Preview questions in ${name}`} aria-expanded={!!position} aria-controls={position?id:undefined} onFocus={()=>{if(skipFocus.current)skipFocus.current=false;else open();}} onClick={open}>{count} questions</button>
    {position&&createPortal(<div ref={popup} id={id} role="dialog" aria-label={`Questions in ${name}`} className="category-question-preview" style={position} onMouseEnter={cancel} onMouseLeave={later} onFocus={cancel} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node)&&!anchor.current?.contains(e.relatedTarget as Node))later();}}>
      <div className="category-preview-heading"><strong>{name}</strong><button aria-label="Close question preview" onClick={close}>×</button></div>
      <div className="category-preview-list" tabIndex={0} aria-label="Scrollable category questions">
        {questions.length?<ol>{questions.map(q=><li key={q.id}><span className="mono">{q.id}</span><p>{q.question??'Question text unavailable.'}</p></li>)}</ol>:<p>No questions available for this category.</p>}
      </div>
    </div>,document.body)}
  </div>;
}
