import test from 'node:test';
import assert from 'node:assert/strict';
import {fitDesk,readDeskLayout} from './deskLayout.js';
test('floating Desk remains reachable after resize and restored geometry is validated',()=>{
 const fit=fitDesk({x:1500,y:900,width:900,height:800},{width:390,height:844});
 assert.equal(fit.width,374);assert.equal(fit.x,8);assert.ok(fit.y+fit.height<=836);
 assert.equal(readDeskLayout({getItem:()=>'{bad'}),null);
 assert.equal(readDeskLayout({getItem:()=>JSON.stringify({mode:'floating',rect:{x:0,y:0,width:'bad',height:700}})}),null);
});
