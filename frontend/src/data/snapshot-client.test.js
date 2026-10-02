import { afterEach, beforeEach, expect, it, vi } from 'vitest';

let instances;
beforeEach(()=>{vi.resetModules();vi.useFakeTimers();instances=[];vi.stubGlobal('Worker',class {
  handlers=new Map();postMessage=vi.fn();terminate=vi.fn();
  constructor(){instances.push(this);}addEventListener(name,fn){this.handlers.set(name,fn);}
  reply(data){this.handlers.get('message')({data});}
});});
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();});

it('ends a stalled search within the hard deadline, stops its worker and supports explicit retry',async()=>{
  const client=await import('./snapshot-client.js');
  const promise=client.snapshotCall('search',{q:'learning'});
  const rejection=expect(promise).rejects.toMatchObject({code:'SNAPSHOT_TIMEOUT',status:504});
  await vi.advanceTimersByTimeAsync(12000);await rejection;
  expect(instances[0].terminate).toHaveBeenCalledOnce();
  const retry=client.snapshotCall('search',{q:'learning'}),message=instances[1].postMessage.mock.calls[0][0];
  instances[1].reply({id:message.id,result:{total:2}});
  expect(await retry).toEqual({total:2});expect(vi.getTimerCount()).toBe(0);
});

it('cleans cancellation timers without timing out an unrelated successful request',async()=>{
  const client=await import('./snapshot-client.js'),controller=new AbortController();
  const cancelled=client.snapshotCall('search',{q:'old'},controller.signal),check=expect(cancelled).rejects.toMatchObject({name:'AbortError'});
  controller.abort();await check;
  const promise=client.snapshotCall('search',{q:'new'}),message=instances[0].postMessage.mock.calls.at(-1)[0];
  instances[0].reply({id:message.id,result:{total:1}});await promise;
  await vi.advanceTimersByTimeAsync(12000);
  expect(instances[0].terminate).not.toHaveBeenCalled();expect(vi.getTimerCount()).toBe(0);
});
