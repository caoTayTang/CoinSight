import test from 'node:test';
import assert from 'node:assert/strict';
import {readDeskLayout} from './deskLayout.js';
test('saved Desk width is clamped and an old floating save falls back to docked',()=>{
 const read=v=>readDeskLayout({getItem:()=>v});
 assert.equal(read('{bad'),null);
 assert.deepEqual(read(JSON.stringify({mode:'floating',rect:{x:0,y:0,width:900,height:700},dockWidth:9000})),{dockWidth:620});
 assert.deepEqual(read(JSON.stringify({dockWidth:'bad'})),{dockWidth:420});
});
