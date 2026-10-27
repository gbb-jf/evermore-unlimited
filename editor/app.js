import {directions, emptyPixels, clone, snesColor, pixel, line, fill, rectangle, copy, paste, flip, patrolPosition, animationFrame} from './pixels.js';

const $ = id => document.getElementById(id);
const state = {characters: new Map(), scene: null, selected: null, npc: 0, view: 'character',
  mode: 'idle', facing: 'south', frame: 0, color: '4', tool: 'pencil', zoom: 16,
  selection: null, clipboard: null, cursor: [16, 16], playing: false, playFrame: 0,
  token: '', cloneSource: null, waypointMode: false, reference: null, image: null, busy: false};
let drawing = null, sceneDrag = null, simulationStart = performance.now();

function entry(document, revision) { return {doc: clone(document), saved: JSON.stringify(document), revision, undo: [], redo: [], external: false}; }
const characterEntry = () => state.characters.get(state.selected);
const character = () => characterEntry()?.doc;
const active = () => state.view === 'scene' ? state.scene : characterEntry();
const dirty = item => item && JSON.stringify(item.doc) !== item.saved;
const clip = () => character().animations[state.mode][state.facing];
const current = () => clip()[Math.min(state.frame, clip().length - 1)];

async function request(path, body, method = 'POST') {
  const options = body === undefined ? {} : {method, headers: {'Content-Type': 'application/json', 'X-Editor-Token': state.token}, body: JSON.stringify(body)};
  const result = await fetch(path, options);
  const data = await result.json();
  if (!result.ok) {
    const error = new Error(data.error || 'Request failed');
    Object.assign(error, data);
    throw error;
  }
  return data;
}
function notice(message, error = false, fields = []) {
  const node = $('notice');
  node.replaceChildren(document.createTextNode(message));
  node.classList.toggle('error', error);
  if (fields.length) {
    const list = document.createElement('ul');
    for (const field of fields.slice(0, 6)) {
      const item = document.createElement('li'); item.textContent = `${field.field}: ${field.message}`; list.append(item);
    }
    node.append(list);
  }
  node.hidden = !message;
}
function failed(error) { notice(error.message, true, error.errors || []); renderStatus(); }
function action(fn) { return (...args) => Promise.resolve().then(() => fn(...args)).catch(failed); }
function history(item = active()) {
  if (!item) return;
  item.undo.push(clone(item.doc));
  if (item.undo.length > 100) item.undo.shift();
  item.redo = [];
}
function change(fn, item = active()) { history(item); fn(item.doc); render(); }
function bindText(id, getValue, setValue, getEntry) {
  let editing = false;
  $(id).onfocus = () => {editing = false;};
  $(id).oninput = () => {
    const value = $(id).value;
    if (value === getValue()) return;
    if (!editing) history(getEntry());
    editing = true; setValue(value);
    // Keep the focused field/caret intact, but make typing immediately saveable.
    if (id === 'character-name') $('character-title').textContent = value;
    renderLibrary(); renderStatus();
  };
  $(id).onchange = () => {editing = false; render();};
}
function undo(redo = false) {
  const item = active(), source = redo ? item.redo : item.undo, destination = redo ? item.undo : item.redo;
  if (!source.length) return;
  destination.push(clone(item.doc)); item.doc = source.pop();
  state.frame = Math.min(state.frame, clip()?.length - 1 || 0);
  state.npc = Math.min(state.npc, state.scene.doc.npcs.length - 1);
  state.selection = null; render();
}
function renderStatus() {
  const count = [...state.characters.values(), state.scene].filter(dirty).length;
  $('save-status').textContent = count ? `${count} unsaved` : 'All changes saved';
  $('save-status').classList.toggle('dirty', count > 0);
  $('save').disabled = !count;
  $('build').disabled = state.busy;
  $('capture').disabled = state.busy;
  $('play').disabled = state.busy;
  $('conflict').hidden = !active()?.external;
}
function drawSprite(context, rows, palette, x, y, scale = 1, alpha = 1) {
  context.save(); context.globalAlpha = alpha;
  rows.forEach((row, py) => [...row].forEach((value, px) => {
    if (value === '.') return;
    context.fillStyle = snesColor(palette[parseInt(value, 16)]);
    context.fillRect(x + px * scale, y + py * scale, scale, scale);
  }));
  context.restore();
}
function thumbnail(canvas, document, facing = 'south', mode = 'idle', frame = 0) {
  canvas.width = 64; canvas.height = 64;
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, 64, 64);
  const frames = document.animations[mode][facing];
  drawSprite(context, frames[frame % frames.length].pixels, document.palette, 0, 0, 2);
}
function renderLibrary() {
  const query = $('search').value.toLowerCase();
  $('character-list').replaceChildren();
  for (const [id, item] of state.characters) {
    if (!(id + item.doc.name).toLowerCase().includes(query)) continue;
    const button = document.createElement('button');
    button.className = 'character-card' + (id === state.selected ? ' active' : '');
    button.setAttribute('role', 'listitem'); button.dataset.id = id;
    const canvas = document.createElement('canvas'); thumbnail(canvas, item.doc);
    const details = document.createElement('div'), name = document.createElement('strong'), detail = document.createElement('small');
    name.textContent = item.doc.name + (dirty(item) ? ' ·' : '');
    detail.textContent = id;
    details.append(name, detail); button.append(canvas, details);
    button.onclick = () => {state.selected = id; state.frame = 0; state.selection = null; state.playing = false; setView('character');};
    $('character-list').append(button);
  }
  $('library-count').textContent = state.characters.size;
}
function renderCanvas() {
  if (!character()) return;
  const canvas = $('pixel-canvas'), z = state.zoom;
  canvas.width = canvas.height = 32 * z;
  const context = canvas.getContext('2d');
  for (let y = 0; y < 32; y++) for (let x = 0; x < 32; x++) {
    context.fillStyle = ((Math.floor(x / 2) + Math.floor(y / 2)) % 2) ? '#3a4037' : '#32382f';
    context.fillRect(x * z, y * z, z, z);
  }
  const index = state.playing ? state.playFrame % clip().length : state.frame;
  if ($('onion').checked && clip().length > 1) drawSprite(context, clip()[(index + clip().length - 1) % clip().length].pixels, character().palette, 0, 0, z, .25);
  drawSprite(context, clip()[index].pixels, character().palette, 0, 0, z);
  if ($('grid').checked) {
    context.strokeStyle = '#0003'; context.lineWidth = 1;
    context.beginPath();
    for (let i = 0; i <= 32; i++) {context.moveTo(i * z + .5, 0); context.lineTo(i * z + .5, canvas.height); context.moveTo(0, i * z + .5); context.lineTo(canvas.width, i * z + .5);}
    context.stroke();
  }
  context.strokeStyle = '#e4bd85'; context.lineWidth = 2;
  context.beginPath(); context.moveTo(16 * z, 32 * z - 9); context.lineTo(16 * z, 32 * z);
  context.moveTo(16 * z - 6, 32 * z - 2); context.lineTo(16 * z + 6, 32 * z - 2); context.stroke();
  if (state.selection) {
    const r = state.selection;
    context.strokeStyle = '#fff'; context.setLineDash([4, 3]);
    context.strokeRect(r.x * z + 1, r.y * z + 1, r.width * z - 2, r.height * z - 2);
  }
  if (document.activeElement === canvas) {
    context.setLineDash([]); context.strokeStyle = '#a6e6be';
    context.strokeRect(state.cursor[0] * z + 1, state.cursor[1] * z + 1, z - 2, z - 2);
  }
  $('cursor-info').textContent = `${state.cursor.join(', ')} · 32 × 32 · foot anchor 16, 32`;
}
function renderPalette() {
  $('palette').replaceChildren();
  character().palette.forEach((color, i) => {
    const button = document.createElement('button');
    button.className = 'swatch' + (i === 0 ? ' transparent' : '') + (state.color === (i ? i.toString(16) : '.') ? ' active' : '');
    button.title = `${i.toString(16)} · ${color}`; button.setAttribute('aria-label', `Palette color ${i.toString(16)}`);
    if (i) button.style.background = snesColor(color);
    const label = document.createElement('span'); label.textContent = i.toString(16); button.append(label);
    button.onclick = () => {state.color = i ? i.toString(16) : '.'; renderPalette();};
    $('palette').append(button);
  });
  const index = state.color === '.' ? 0 : parseInt(state.color, 16), color = character().palette[index];
  $('color-picker').disabled = $('color-hex').disabled = !index;
  $('color-picker').value = index ? color : '#000000'; $('color-hex').value = index ? color : 'transparent';
  $('color-index').textContent = index.toString(16);
  $('snes-color').textContent = index ? `SNES color: ${snesColor(color)}` : 'Index 0 is always transparent';
}
function renderCharacter() {
  if (!character()) return;
  state.frame = Math.max(0, Math.min(state.frame, clip().length - 1));
  $('character-title').textContent = character().name;
  $('character-name').value = character().name; $('description').value = character().description || '';
  $('character-id').textContent = `assets/characters/${state.selected}.json`;
  $('mode').value = state.mode;
  $('directions').replaceChildren();
  for (const direction of directions) {
    const button = document.createElement('button'); button.textContent = direction[0].toUpperCase();
    button.title = direction; button.setAttribute('aria-label', `Face ${direction}`);
    button.setAttribute('aria-pressed', state.facing === direction);
    button.onclick = () => {state.facing = direction; state.frame = 0; state.selection = null; renderCharacter();};
    $('directions').append(button);
  }
  $('duration').value = current().duration;
  $('frames').replaceChildren();
  clip().forEach((frame, i) => {
    const button = document.createElement('button'); button.className = 'frame-card' + (state.frame === i ? ' active' : '');
    button.setAttribute('aria-label', `Select frame ${i + 1}`);
    const canvas = document.createElement('canvas'); thumbnail(canvas, character(), state.facing, state.mode, i);
    button.append(canvas, document.createTextNode(`${i + 1} · ${frame.duration}t`));
    button.onclick = () => {state.frame = i; state.playing = false; renderCharacter();}; $('frames').append(button);
  });
  $('frame-delete').disabled = clip().length === 1;
  $('frame-add').disabled = $('frame-duplicate').disabled = clip().length === 16;
  $('frame-left').disabled = state.frame === 0; $('frame-right').disabled = state.frame === clip().length - 1;
  $('animate').textContent = state.playing ? 'Ⅱ Pause' : '▶ Preview'; $('animate').setAttribute('aria-pressed', state.playing);
  $('undo').disabled = !characterEntry().undo.length; $('redo').disabled = !characterEntry().redo.length;
  renderPalette(); renderPreviews(); renderCanvas();
}
function renderPreviews() {
  $('native-previews').replaceChildren();
  for (const direction of directions) {
    const wrapper = document.createElement('div'), canvas = document.createElement('canvas'), label = document.createElement('small');
    thumbnail(canvas, character(), direction, state.mode, state.playing ? state.playFrame : state.frame);
    label.textContent = direction[0].toUpperCase(); wrapper.append(canvas, label); $('native-previews').append(wrapper);
  }
}
function renderTools() {
  $('tools').replaceChildren();
  for (const [name, key] of [['pencil', 'B'], ['eraser', 'E'], ['fill', 'G'], ['pick', 'I'], ['select', 'M']]) {
    const button = document.createElement('button'); button.textContent = `${name[0].toUpperCase() + name.slice(1)} ${key}`;
    button.title = `${name} (${key})`; button.setAttribute('aria-pressed', state.tool === name);
    button.onclick = () => {state.tool = name; renderTools();}; $('tools').append(button);
  }
}
function setView(view) {
  state.view = view;
  $('character-workspace').hidden = $('character-properties').hidden = view !== 'character';
  $('scene-workspace').hidden = $('scene-properties').hidden = view !== 'scene';
  $('tab-character').classList.toggle('active', view === 'character'); $('tab-scene').classList.toggle('active', view === 'scene');
  render();
}
function render() {renderLibrary(); renderTools(); renderCharacter(); renderSceneProperties(); renderScene(); renderStatus();}

function canvasPoint(event) {
  const bounds = $('pixel-canvas').getBoundingClientRect();
  return [Math.max(0, Math.min(31, Math.floor((event.clientX - bounds.left) * 32 / bounds.width))),
          Math.max(0, Math.min(31, Math.floor((event.clientY - bounds.top) * 32 / bounds.height)))];
}
function applyTool(point, previous = point, erase = false) {
  const [x, y] = point, rows = current().pixels, color = erase || state.tool === 'eraser' ? '.' : state.color;
  if (state.tool === 'fill') fill(rows, x, y, color);
  else if (state.tool === 'pick') {state.color = rows[y][x]; renderPalette();}
  else if (state.tool !== 'select') line(rows, previous, point, color);
}
$('pixel-canvas').oncontextmenu = event => event.preventDefault();
$('pixel-canvas').onpointerdown = event => {
  event.preventDefault(); $('pixel-canvas').focus(); state.playing = false;
  const point = canvasPoint(event); state.cursor = point;
  drawing = {first: point, last: point, erase: event.button === 2};
  if (!['pick', 'select'].includes(state.tool)) history(characterEntry());
  if (state.tool === 'select') state.selection = rectangle(point, point); else applyTool(point, point, drawing.erase);
  $('pixel-canvas').setPointerCapture(event.pointerId); renderCanvas(); renderStatus();
};
$('pixel-canvas').onpointermove = event => {
  state.cursor = canvasPoint(event);
  if (drawing) {
    if (state.tool === 'select') state.selection = rectangle(drawing.first, state.cursor);
    else if (!['fill', 'pick'].includes(state.tool)) applyTool(state.cursor, drawing.last, drawing.erase);
    drawing.last = state.cursor;
  }
  renderCanvas();
};
$('pixel-canvas').onpointerup = () => {drawing = null; renderLibrary(); renderCharacter(); renderStatus();};
$('pixel-canvas').onpointercancel = () => {drawing = null;};
$('zoom').oninput = () => {state.zoom = Number($('zoom').value); $('zoom-value').textContent = state.zoom + '×'; renderCanvas();};
$('grid').onchange = $('onion').onchange = renderCanvas;
$('mode').onchange = () => {state.mode = $('mode').value; state.frame = 0; state.playFrame = 0; state.selection = null; renderCharacter();};
$('animate').onclick = () => {state.playing = !state.playing; state.playFrame = state.frame; renderCharacter();};
$('undo').onclick = () => undo(); $('redo').onclick = () => undo(true);
$('scene-undo').onclick = () => undo(); $('scene-redo').onclick = () => undo(true);
$('flip-x').onclick = () => change(() => flip(current().pixels, 'x', state.selection), characterEntry());
$('flip-y').onclick = () => change(() => flip(current().pixels, 'y', state.selection), characterEntry());
$('duration').onchange = () => {
  const value = Number($('duration').value);
  if (!Number.isInteger(value) || value < 1 || value > 120) return notice('Frame duration must be 1–120 ticks.', true);
  change(() => {current().duration = value;}, characterEntry());
};
for (const [id, duplicate] of [['frame-add', false], ['frame-duplicate', true]]) $(id).onclick = () => change(() => {
  const frame = duplicate ? clone(current()) : {duration: 8, pixels: emptyPixels()};
  clip().splice(state.frame + 1, 0, frame); state.frame++;
}, characterEntry());
$('frame-delete').onclick = () => change(() => {clip().splice(state.frame, 1); state.frame = Math.max(0, state.frame - 1);}, characterEntry());
for (const [id, delta] of [['frame-left', -1], ['frame-right', 1]]) $(id).onclick = () => change(() => {
  const at = state.frame, other = at + delta; [clip()[at], clip()[other]] = [clip()[other], clip()[at]]; state.frame = other;
}, characterEntry());
function editColor(value) {
  if (!/^#[0-9a-f]{6}$/i.test(value)) return notice('Use a six-digit hex color, such as #c18c52.', true);
  change(doc => {doc.palette[parseInt(state.color, 16)] = value.toLowerCase();}, characterEntry());
}
$('color-picker').onchange = () => editColor($('color-picker').value);
$('color-hex').onchange = () => editColor($('color-hex').value);
$('search').oninput = renderLibrary;
$('tab-character').onclick = () => setView('character'); $('tab-scene').onclick = () => setView('scene');

function createDialog(source = null) {
  state.cloneSource = source;
  $('create-heading').textContent = source ? 'Duplicate character' : 'New character';
  $('create-name').value = source ? character().name + ' copy' : 'New character';
  $('create-id').value = source ? source + '-copy' : 'new-character';
  $('create-error').textContent = ''; $('create-dialog').showModal(); $('create-name').focus();
}
$('new-character').onclick = () => createDialog(); $('clone-character').onclick = () => createDialog(state.selected);
$('create-cancel').onclick = () => $('create-dialog').close();
$('create-name').oninput = () => {$('create-id').value = $('create-name').value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48);};
$('create-form').onsubmit = async event => {
  event.preventDefault();
  try {
    if (state.cloneSource && dirty(characterEntry())) await saveOne('characters', characterEntry());
    const result = await request('/api/create', {source: state.cloneSource, id: $('create-id').value, name: $('create-name').value});
    state.characters.set(result.document.id, entry(result.document, result.revision)); state.selected = result.document.id;
    $('create-dialog').close(); state.frame = 0; setView('character'); notice('Character created.');
  } catch (error) {$('create-error').textContent = error.message;}
};
async function saveOne(kind, item) {
  const result = await request(`/api/doc/${kind}/${item.doc.id}`, {document: item.doc, revision: item.revision}, 'PUT');
  item.revision = result.revision; item.saved = JSON.stringify(result.document); item.external = false;
}
async function saveAll() {
  for (const item of state.characters.values()) if (dirty(item)) await saveOne('characters', item);
  if (dirty(state.scene)) await saveOne('scenes', state.scene);
  render(); notice('All changes saved.');
}
$('save').onclick = action(saveAll);
$('reload-document').onclick = action(async () => {
  const item = active(), kind = state.view === 'scene' ? 'scenes' : 'characters';
  if (dirty(item) && !confirm('Reload from disk and discard this document’s unsaved edits?')) return;
  const result = await request(`/api/doc/${kind}/${item.doc.id}`);
  if (kind === 'scenes') state.scene = entry(result.document, result.revision);
  else state.characters.set(result.document.id, entry(result.document, result.revision));
  render(); notice('Reloaded from disk.');
});
async function startJob(job) {
  if (state.busy) return;
  if (job === 'build') await saveAll();
  state.busy = true; renderStatus();
  try {
    await request('/api/' + job, {});
    notice(job === 'build' ? 'Building the ROM from saved character and scene files…' : 'Capturing a station reference from your original ROM. This takes a few seconds…');
    while (true) {
      await new Promise(resolve => setTimeout(resolve, 500));
      const result = await request('/api/job');
      if (result.running) continue;
      if (result.status !== 'passed') throw new Error(result.error || 'Operation failed');
      await refresh();
      notice(job === 'build' ? 'ROM built. Open build/evermore-npc.sfc in Luna and start a fresh game.' : 'Station reference captured.');
      break;
    }
  } finally {
    state.busy = false; renderStatus();
  }
}
$('build').onclick = action(() => startJob('build')); $('capture').onclick = action(() => startJob('capture'));
$('play').onclick = action(async () => {await request('/api/play', {}); notice('Opened the built ROM in Luna. Start a fresh game.');});
$('help').onclick = () => $('help-dialog').showModal(); $('help-close').onclick = () => $('help-dialog').close();
function download(data, name, type) {
  const url = URL.createObjectURL(new Blob([data], {type})), link = document.createElement('a');
  link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('export-json').onclick = () => download(JSON.stringify(active().doc, null, 2) + '\n', active().doc.id + '.json', 'application/json');
$('import-json').onclick = () => {$('json-file').value = ''; $('json-file').click();};
$('json-file').onchange = action(async () => {
  const file = $('json-file').files[0]; if (!file) return;
  const document = JSON.parse(await file.text()), kind = document.npcs ? 'scenes' : 'characters';
  const item = kind === 'scenes' ? state.scene : state.characters.get(document.id);
  const result = await request(`/api/doc/${kind}/${document.id}`, {document, revision: item?.revision ?? null}, 'PUT');
  if (kind === 'scenes') {state.scene = entry(result.document, result.revision); setView('scene');}
  else {state.characters.set(document.id, entry(result.document, result.revision)); state.selected = document.id; setView('character');}
  notice('JSON imported and saved.');
});
$('export-png').onclick = action(async () => {
  await saveOne('characters', characterEntry());
  const response = await fetch(`/api/export/${state.selected}?mode=${state.mode}`);
  if (!response.ok) throw new Error('PNG export failed');
  download(await response.arrayBuffer(), `${state.selected}-${state.mode}.png`, 'image/png'); renderStatus();
});
$('import-png').onclick = () => {$('png-file').value = ''; $('png-file').click();};
$('png-file').onchange = action(async () => {
  const file = $('png-file').files[0]; if (!file) return;
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = ''; bytes.forEach(byte => {binary += String.fromCharCode(byte);});
  const result = await request('/api/import-png', {document: character(), png: btoa(binary), mode: state.mode, mapping: $('nearest').checked ? 'nearest' : 'exact'});
  history(characterEntry()); characterEntry().doc = result.document; state.frame = 0; render(); notice('PNG imported into the current animation. Save when ready.');
});

function selectedNPC() {return state.scene?.doc.npcs[state.npc];}
function renderSceneProperties() {
  const npc = selectedNPC();
  for (const id of ['npc-id', 'npc-character', 'npc-x', 'npc-y', 'npc-facing', 'npc-dialogue', 'movement', 'remove-npc', 'add-waypoint']) $(id).disabled = !npc;
  $('npc-character').replaceChildren();
  for (const [id, item] of state.characters) {
    const option = document.createElement('option'); option.value = id; option.textContent = item.doc.name; $('npc-character').append(option);
  }
  $('npc-list').replaceChildren();
  state.scene.doc.npcs.forEach((item, index) => {
    const button = document.createElement('button'); button.className = 'npc-badge' + (index === state.npc ? ' active' : '');
    button.textContent = `${item.id} · ${item.movement.mode}`; button.onclick = () => {state.npc = index; renderSceneProperties(); renderScene();}; $('npc-list').append(button);
  });
  $('scene-budget').textContent = `${state.scene.doc.npcs.length}/8 NPCs · ${new Set(state.scene.doc.npcs.map(n => n.character)).size}/2 palettes`;
  $('add-npc').disabled = state.scene.doc.npcs.length >= 8;
  $('scene-undo').disabled = !state.scene.undo.length; $('scene-redo').disabled = !state.scene.redo.length;
  $('waypoints').replaceChildren();
  if (!npc) {for (const id of ['npc-id', 'npc-x', 'npc-y', 'npc-dialogue']) $(id).value = ''; return;}
  $('npc-id').value = npc.id; $('npc-character').value = npc.character; $('npc-x').value = npc.position.x; $('npc-y').value = npc.position.y;
  $('npc-facing').value = npc.facing; $('npc-dialogue').value = npc.dialogue; $('movement').value = npc.movement.mode;
  npc.movement.waypoints.forEach((point, index) => {
    const container = document.createElement('div'); container.className = 'waypoint';
    const heading = document.createElement('div'); heading.className = 'waypoint-heading'; heading.textContent = `Waypoint ${index + 1}`;
    const controls = document.createElement('div');
    for (const [text, fn] of [['↑', () => {if (index) [npc.movement.waypoints[index - 1], npc.movement.waypoints[index]] = [point, npc.movement.waypoints[index - 1]];}], ['×', () => npc.movement.waypoints.splice(index, 1)]]) {
      const button = document.createElement('button'); button.textContent = text; button.title = text === '↑' ? 'Move waypoint earlier' : 'Remove waypoint';
      button.onclick = () => change(fn, state.scene); controls.append(button);
    }
    heading.append(controls); container.append(heading);
    const fields = document.createElement('div'); fields.className = 'two-fields';
    for (const key of ['x', 'y', 'pause']) {
      const label = document.createElement('label'), input = document.createElement('input'); label.textContent = key === 'pause' ? 'Pause ticks' : key.toUpperCase();
      input.type = 'number'; input.value = point[key]; input.step = key === 'pause' ? 1 : 8;
      input.setAttribute('aria-label', `Waypoint ${index + 1} ${key}`);
      input.onchange = () => {const value = Number(input.value); change(() => {point[key] = value;}, state.scene);};
      label.append(input); fields.append(label);
    }
    container.append(fields); $('waypoints').append(container);
  });
}
const sceneOrigin = () => state.reference || {x: 368, y: 128};
function scenePoint(event) {
  const bounds = $('scene-canvas').getBoundingClientRect(), origin = sceneOrigin();
  return {x: Math.max(400, Math.min(592, Math.round(((event.clientX - bounds.left) * 256 / bounds.width + origin.x) / 8) * 8)),
          y: Math.max(248, Math.min(320, Math.round(((event.clientY - bounds.top) * 192 / bounds.height + origin.y) / 8) * 8))};
}
function renderScene() {
  if (!state.scene) return;
  const canvas = $('scene-canvas'), context = canvas.getContext('2d'), origin = sceneOrigin(), scale = 3;
  context.imageSmoothingEnabled = false; context.fillStyle = '#252e25'; context.fillRect(0, 0, 768, 576);
  if (state.image) context.drawImage(state.image, 0, 0, 256, 192, 0, 0, 768, 576);
  else {context.fillStyle = '#adbca2'; context.font = '12px system-ui'; context.fillText('Capture a ROM reference to see the station underneath your NPCs.', 30, 50);}
  const transform = point => [(point.x - origin.x) * scale, (point.y - origin.y) * scale];
  const [floorX, floorY] = transform({x: 400, y: 248});
  context.fillStyle = '#8dcc9022'; context.fillRect(floorX, floorY, 192 * scale, 72 * scale);
  context.strokeStyle = '#bdd8a633'; context.lineWidth = 1; context.beginPath();
  for (let x = 0; x <= 256; x += 8) {context.moveTo(x * scale, 0); context.lineTo(x * scale, 576);}
  for (let y = 0; y <= 192; y += 8) {context.moveTo(0, y * scale); context.lineTo(768, y * scale);} context.stroke();
  const npc = selectedNPC();
  if (npc) {
    const points = [npc.position, ...npc.movement.waypoints];
    if (points.length > 1) points.push(npc.movement.waypoints[0]);
    context.strokeStyle = '#ffd79a'; context.lineWidth = 2; context.beginPath();
    points.forEach((point, i) => {
      const [x, y] = transform(point);
      if (!i) context.moveTo(x, y); else {const previous = points[i - 1]; context.lineTo(x, transform(previous)[1]); context.lineTo(x, y);}
    }); context.stroke();
    npc.movement.waypoints.forEach((point, i) => {
      const [x, y] = transform(point); context.fillStyle = '#e6b878'; context.beginPath(); context.arc(x, y, 8, 0, Math.PI * 2); context.fill();
      context.fillStyle = '#242a20'; context.font = 'bold 10px system-ui'; context.fillText(String(i + 1), x - 3, y + 4);
    });
  }
  state.scene.doc.npcs.forEach((npc, index) => {
    const document = state.characters.get(npc.character)?.doc; if (!document) return;
    const position = $('simulate').checked ? patrolPosition(npc, Math.floor((performance.now() - simulationStart) * .06)) : npc.position;
    const [x, y] = transform(position), facing = position.facing || npc.facing, mode = position.moving ? 'walk' : 'idle';
    const frames = document.animations[mode][facing];
    const frame = animationFrame(frames, (performance.now() - simulationStart) * .06);
    drawSprite(context, frames[frame].pixels, document.palette, x - 16 * scale, y - 32 * scale, scale);
    context.strokeStyle = index === state.npc ? '#ffe2b1' : '#a2d4b4'; context.lineWidth = 2;
    context.strokeRect(x - 12 * scale, y - 32 * scale, 24 * scale, 32 * scale);
    context.font = 'bold 11px system-ui'; const width = context.measureText(npc.id).width;
    context.fillStyle = '#151c15e0'; context.fillRect(x - width / 2 - 5, y + 5, width + 10, 18);
    context.fillStyle = '#f6e6c9'; context.fillText(npc.id, x - width / 2, y + 18);
  });
  $('add-waypoint').classList.toggle('active', state.waypointMode);
}
$('scene-canvas').onpointerdown = event => {
  const point = scenePoint(event), npc = selectedNPC(); $('simulate').checked = false;
  if (state.waypointMode && npc) {
    if (npc.movement.waypoints.length >= 16) return notice('Use at most 16 waypoints.', true);
    change(() => {npc.movement.waypoints.push({...point, pause: 30}); npc.movement.mode = 'patrol';}, state.scene);
    return;
  }
  if (npc) {
    const index = npc.movement.waypoints.findIndex(p => Math.abs(p.x - point.x) < 6 && Math.abs(p.y - point.y) < 6);
    if (index >= 0) {history(state.scene); sceneDrag = {type: 'waypoint', index}; $('scene-canvas').setPointerCapture(event.pointerId); return;}
  }
  const selected = state.scene.doc.npcs.findIndex(n => Math.abs(n.position.x - point.x) < 18 && point.y <= n.position.y + 8 && point.y >= n.position.y - 32);
  if (selected >= 0) {state.npc = selected; history(state.scene); sceneDrag = {type: 'npc'}; $('scene-canvas').setPointerCapture(event.pointerId); renderSceneProperties(); renderScene();}
};
$('scene-canvas').onpointermove = event => {
  if (!sceneDrag || !selectedNPC()) return;
  const point = scenePoint(event), npc = selectedNPC();
  if (sceneDrag.type === 'npc') npc.position = point;
  else Object.assign(npc.movement.waypoints[sceneDrag.index], point);
  renderSceneProperties(); renderScene(); renderStatus();
};
$('scene-canvas').onpointerup = () => {sceneDrag = null;};
$('scene-canvas').onpointercancel = () => {sceneDrag = null;};
$('add-waypoint').onclick = () => {state.waypointMode = !state.waypointMode; $('scene-hint').textContent = state.waypointMode ? 'Click the station floor to add a waypoint. Click “Place waypoint” again to finish.' : 'Drag an NPC or waypoint to move it.'; renderScene();};
$('add-npc').onclick = () => change(doc => {
  const used = new Set(doc.npcs.map(n => n.id)); let number = 1; while (used.has(`npc-${number}`)) number++;
  const characters = new Set(doc.npcs.map(n => n.character));
  const character = characters.size >= 2 && !characters.has(state.selected) ? doc.npcs[0].character : state.selected;
  let position = {x: 416, y: 304};
  for (const x of [416, 448, 480, 512, 544, 576]) if (!doc.npcs.some(n => Math.abs(n.position.x - x) < 24 && Math.abs(n.position.y - 304) < 24)) {position = {x, y: 304}; break;}
  doc.npcs.push({id: `npc-${number}`, character, dialogue: 'Hello from Evermore!', position, facing: 'south', movement: {mode: 'stationary', waypoints: []}});
  state.npc = doc.npcs.length - 1;
}, state.scene);
$('remove-npc').onclick = () => change(doc => {doc.npcs.splice(state.npc, 1); state.npc = Math.max(0, state.npc - 1);}, state.scene);
for (const [id, field] of [['npc-character', 'character'], ['npc-facing', 'facing']]) $(id).onchange = () => {
  const value = $(id).value; change(() => {selectedNPC()[field] = value;}, state.scene);
};
for (const [id, field] of [['npc-x', 'x'], ['npc-y', 'y']]) $(id).onchange = () => {const value = Number($(id).value); change(() => {selectedNPC().position[field] = value;}, state.scene);};
$('movement').onchange = () => {
  const value = $('movement').value;
  change(() => {
    const npc = selectedNPC(); npc.movement.mode = value;
    if (value === 'patrol' && npc.movement.waypoints.length < 2) npc.movement.waypoints = [{...npc.position, pause: 30}, {x: npc.position.x > 560 ? npc.position.x - 32 : npc.position.x + 32, y: npc.position.y, pause: 30}];
  }, state.scene);
};
$('simulate').onchange = () => {simulationStart = performance.now(); renderScene();};

bindText('character-name', () => character().name, value => {character().name = value;}, characterEntry);
bindText('description', () => character().description || '', value => {character().description = value;}, characterEntry);
bindText('npc-id', () => selectedNPC().id, value => {selectedNPC().id = value;}, () => state.scene);
bindText('npc-dialogue', () => selectedNPC().dialogue, value => {selectedNPC().dialogue = value;}, () => state.scene);

window.addEventListener('keydown', event => {
  const modifier = event.ctrlKey || event.metaKey, key = event.key.toLowerCase();
  if (modifier && key === 's') {event.preventDefault(); action(saveAll)(); return;}
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName) || document.querySelector('dialog[open]')) return;
  if (modifier && key === 'z') {event.preventDefault(); undo(event.shiftKey); return;}
  if (state.view !== 'character' || !character()) return;
  if (modifier && key === 'c') {event.preventDefault(); state.clipboard = copy(current().pixels, state.selection || undefined); notice('Pixels copied. Paste at the cursor or selection.'); return;}
  if (modifier && key === 'v' && state.clipboard) {event.preventDefault(); change(() => paste(current().pixels, state.clipboard, state.selection?.x ?? state.cursor[0], state.selection?.y ?? state.cursor[1]), characterEntry()); return;}
  const tools = {b: 'pencil', e: 'eraser', g: 'fill', i: 'pick', m: 'select'};
  if (tools[key]) {state.tool = tools[key]; renderTools();}
  if (document.activeElement === $('pixel-canvas')) {
    const movements = {arrowleft: [-1, 0], arrowright: [1, 0], arrowup: [0, -1], arrowdown: [0, 1]};
    if (movements[key]) {event.preventDefault(); state.cursor = state.cursor.map((v, i) => Math.max(0, Math.min(31, v + movements[key][i]))); renderCanvas();}
    if (['enter', 'delete', 'backspace'].includes(key)) {event.preventDefault(); change(() => pixel(current().pixels, ...state.cursor, key === 'enter' ? state.color : '.'), characterEntry());}
  }
});
window.addEventListener('beforeunload', event => {if ([...state.characters.values(), state.scene].some(dirty)) {event.preventDefault(); event.returnValue = '';}});

async function refresh(initial = false) {
  const project = await request('/api/project'); state.token = project.token;
  let workspaceChanged = false;
  for (const result of project.characters) {
    const id = result.document.id, existing = state.characters.get(id);
    if (!existing) state.characters.set(id, entry(result.document, result.revision));
    else if (existing.revision !== result.revision) {
      if (dirty(existing)) existing.external = true;
      else {state.characters.set(id, entry(result.document, result.revision)); workspaceChanged = true;}
    }
  }
  if (!state.scene) state.scene = entry(project.scene.document, project.scene.revision);
  else if (state.scene.revision !== project.scene.revision) {
    if (dirty(state.scene)) state.scene.external = true;
    else {state.scene = entry(project.scene.document, project.scene.revision); workspaceChanged = true;}
  }
  state.selected ||= state.characters.keys().next().value;
  if (project.reference && (!state.reference || JSON.stringify(project.reference) !== JSON.stringify(state.reference))) {
    state.reference = project.reference;
    const image = new Image(); image.onload = () => {state.image = image; renderScene();}; image.src = '/api/reference.png?' + Date.now();
  }
  if (project.build) $('build-status').textContent = `build/evermore-npc.sfc · ${project.build.target.sha256.slice(0, 12)}… · start a fresh game`;
  if (initial || workspaceChanged) render(); else {renderLibrary(); renderStatus();}
}
let previousFrameTime = performance.now(), previousSceneTime = 0;
function animationLoop(time) {
  if (state.playing && character()) {
    const duration = clip()[state.playFrame % clip().length].duration * 1000 / 60;
    if (time - previousFrameTime > duration) {previousFrameTime = time; state.playFrame++; renderCanvas(); renderPreviews();}
  } else previousFrameTime = time;
  if (state.view === 'scene' && time - previousSceneTime > 80) {previousSceneTime = time; renderScene();}
  requestAnimationFrame(animationLoop);
}
await refresh(true).catch(failed);
setInterval(() => refresh().catch(error => {if (!state.busy) failed(error);}), 3000);
requestAnimationFrame(animationLoop);
