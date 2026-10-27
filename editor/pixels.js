export const directions = ['north', 'east', 'south', 'west'];
export const emptyPixels = () => Array(32).fill('.'.repeat(32));
export const clone = value => structuredClone(value);
export function snesColor(hex) {
  if (hex === 'transparent') return null;
  const channels = [1, 3, 5].map(at => Math.floor(parseInt(hex.slice(at, at + 2), 16) / 8) * 255 / 31);
  return `rgb(${channels.map(Math.floor).join(',')})`;
}
export function pixel(rows, x, y, color) {
  if (x < 0 || x >= 32 || y < 0 || y >= 32) return;
  rows[y] = rows[y].slice(0, x) + color + rows[y].slice(x + 1);
}
export function line(rows, a, b, color) {
  let [x, y] = a, [x2, y2] = b;
  const dx = Math.abs(x2 - x), sx = x < x2 ? 1 : -1;
  const dy = -Math.abs(y2 - y), sy = y < y2 ? 1 : -1;
  let error = dx + dy;
  while (true) {
    pixel(rows, x, y, color);
    if (x === x2 && y === y2) break;
    const doubled = 2 * error;
    if (doubled >= dy) { error += dy; x += sx; }
    if (doubled <= dx) { error += dx; y += sy; }
  }
}
export function fill(rows, x, y, color) {
  const original = rows[y][x];
  if (original === color) return;
  const pending = [[x, y]];
  while (pending.length) {
    const [px, py] = pending.pop();
    if (px < 0 || py < 0 || px >= 32 || py >= 32 || rows[py][px] !== original) continue;
    pixel(rows, px, py, color);
    pending.push([px - 1, py], [px + 1, py], [px, py - 1], [px, py + 1]);
  }
}
export function rectangle(a, b) {
  return {x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]),
          width: Math.abs(a[0] - b[0]) + 1, height: Math.abs(a[1] - b[1]) + 1};
}
export function copy(rows, area = {x: 0, y: 0, width: 32, height: 32}) {
  area ||= {x: 0, y: 0, width: 32, height: 32};
  return rows.slice(area.y, area.y + area.height).map(row => row.slice(area.x, area.x + area.width));
}
export function paste(rows, copied, x, y) {
  copied.forEach((row, dy) => [...row].forEach((value, dx) => pixel(rows, x + dx, y + dy, value)));
}
export function flip(rows, axis, area = {x: 0, y: 0, width: 32, height: 32}) {
  area ||= {x: 0, y: 0, width: 32, height: 32};
  let selected = copy(rows, area);
  selected = axis === 'x' ? selected.map(row => [...row].reverse().join('')) : selected.reverse();
  paste(rows, selected, area.x, area.y);
}
export function animationFrame(frames, elapsedTicks) {
  let remaining = Math.max(0, elapsedTicks) % frames.reduce((sum, frame) => sum + frame.duration, 0);
  for (let i = 0; i < frames.length; i++) {
    if (remaining < frames[i].duration) return i;
    remaining -= frames[i].duration;
  }
  return 0;
}
export function patrolPosition(npc, elapsedTicks) {
  const route = npc.movement.waypoints;
  if (npc.movement.mode !== 'patrol' || route.length < 2) return {...npc.position, facing: npc.facing, moving: false};
  let current = {...npc.position}, remaining = Math.max(0, elapsedTicks), facing = npc.facing;
  const arrivalFacing = (from, to, fallback) => to.y !== from.y ? (to.y > from.y ? 'south' : 'north') :
    to.x !== from.x ? (to.x > from.x ? 'east' : 'west') : fallback;
  const segment = target => {
    const dx = target.x - current.x, dy = target.y - current.y;
    if (remaining < Math.abs(dx)) return {x: current.x + Math.sign(dx) * remaining, y: current.y, moving: true, facing: dx > 0 ? 'east' : 'west'};
    remaining -= Math.abs(dx);
    if (remaining < Math.abs(dy)) return {x: target.x, y: current.y + Math.sign(dy) * remaining, moving: true, facing: dy > 0 ? 'south' : 'north'};
    remaining -= Math.abs(dy);
    facing = arrivalFacing(current, target, facing);
    current = {...target};
    if (remaining < target.pause) return {...current, facing, moving: false};
    remaining -= target.pause;
    return null;
  };
  // The first leg starts at the placed NPC, just as the native patrol does.
  const first = segment(route[0]);
  if (first) return first;
  const length = route.reduce((sum, target, i) => {
    const previous = route[(i + route.length - 1) % route.length];
    return sum + Math.abs(target.x - previous.x) + Math.abs(target.y - previous.y) + target.pause;
  }, 0);
  const completedCycles = Math.floor(remaining / Math.max(1, length));
  if (completedCycles) facing = arrivalFacing(route.at(-1), route[0], facing);
  remaining %= Math.max(1, length);
  for (let i = 1; i <= route.length; i++) {
    const target = route[i % route.length];
    const position = segment(target);
    if (position) return position;
  }
  return {...current, facing, moving: false};
}
