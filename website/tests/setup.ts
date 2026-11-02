import {vi} from 'vitest';
Object.defineProperty(window,'matchMedia',{writable:true,value:vi.fn().mockImplementation(()=>({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()}))});
Object.defineProperty(window,'scrollTo',{value:vi.fn()});
Object.defineProperty(HTMLElement.prototype,'scrollIntoView',{value:vi.fn()});
Object.defineProperty(globalThis,'ResizeObserver',{value:class{observe(){}unobserve(){}disconnect(){}}});
Object.defineProperty(URL,'createObjectURL',{value:vi.fn(()=> 'blob:test')});Object.defineProperty(URL,'revokeObjectURL',{value:vi.fn()});
