import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyPixels, line, fill, copy, paste, flip, rectangle, snesColor, patrolPosition, animationFrame} from '../editor/pixels.js';

test('continuous brush strokes do not leave holes', () => {
  const rows = emptyPixels(); line(rows, [0, 0], [31, 31], 'a');
  for (let i = 0; i < 32; i++) assert.equal(rows[i][i], 'a');
});
test('fill respects a closed boundary and leaves other regions untouched', () => {
  const rows = emptyPixels();
  for (const [a,b] of [[[4,4],[12,4]],[[12,4],[12,12]],[[12,12],[4,12]],[[4,12],[4,4]]]) line(rows,a,b,'1');
  fill(rows, 7, 7, 'c'); assert.equal(rows[5][5], 'c'); assert.equal(rows[3][3], '.'); assert.equal(rows[4][4], '1');
});
test('selection copy/paste clips to the canvas and flips only the selection', () => {
  const rows = emptyPixels(); line(rows,[1,1],[3,1],'3');
  const selected = copy(rows, rectangle([1,1],[3,2])); paste(rows, selected, 30, 30);
  assert.equal(rows[30].slice(30), '33'); assert.equal(rows[31].slice(30), '..');
  flip(rows,'y',{x:1,y:1,width:3,height:2}); assert.equal(rows[1].slice(1,4),'...'); assert.equal(rows[2].slice(1,4),'333');
  flip(rows,'x',null); assert.equal(rows[2].slice(28,31),'333');
});
test('SNES colors use native five-bit channel precision', () => {
  assert.equal(snesColor('#ffffff'),'rgb(255,255,255)'); assert.equal(snesColor('#070707'),'rgb(0,0,0)'); assert.equal(snesColor('transparent'),null);
});
test('patrol preview pauses and then follows its route in both directions', () => {
  const npc={position:{x:416,y:304},movement:{mode:'patrol',waypoints:[{x:416,y:304,pause:10},{x:448,y:304,pause:10}]}};
  assert.equal(patrolPosition(npc,5).moving,false);
  assert.equal(patrolPosition(npc,20).x,426);
  assert.equal(patrolPosition(npc,45).x,448);
  assert.equal(patrolPosition(npc,60).facing,'west');
});
test('patrol preview starts at the placed actor and keeps facing during pauses', () => {
  const npc={position:{x:400,y:304},facing:'north',movement:{mode:'patrol',waypoints:[{x:416,y:304,pause:10},{x:448,y:304,pause:10}]}};
  assert.deepEqual(patrolPosition(npc,8),{x:408,y:304,moving:true,facing:'east'});
  assert.equal(patrolPosition(npc,18).moving,false);
  assert.equal(patrolPosition(npc,18).facing,'east');
  assert.equal(patrolPosition(npc,96).facing,'west');
});
test('animation preview honors unequal authored durations and loops', () => {
  const frames=[{duration:2},{duration:10},{duration:1}];
  assert.equal(animationFrame(frames,1),0);
  assert.equal(animationFrame(frames,2),1);
  assert.equal(animationFrame(frames,11),1);
  assert.equal(animationFrame(frames,12),2);
  assert.equal(animationFrame(frames,13),0);
});
