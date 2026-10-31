"""Opening-only gamemaster bytecode and scoped native text bridge.

All offsets are unheadered file offsets. The companion supplies dialogue only;
controller input and ROM scripts own encounter selection and progression.
"""
import struct

from character_rom import Asm
from snes_graphics import u16, u24

SCRIPT = 0x338000
TEXT = 0x330000
TEXT_HOOK = 0x344000
MAILBOX = 0x28E0
MAGIC = 0x4D47
VERSION = 1
REQUEST = MAILBOX + 4
STATUS = MAILBOX + 6
CHOICE = MAILBOX + 8
ELAPSED = MAILBOX + 10
BOSS = MAILBOX + 12
CLAW1 = MAILBOX + 14
CLAW2 = MAILBOX + 16
STEP = MAILBOX + 18
TARGET_X = MAILBOX + 20
TARGET_Y = MAILBOX + 22
PROJECTILE = MAILBOX + 24
TEXT_RAM = 0x7FF000
TEXT_CAPACITY = 512
DYNAMIC_TEXT = 0xFFF9
MENU_TEXT = 0xFFFC
BOSSES = ('Thraxx', 'Salabog', 'Magmar')


def const(n):
    return bytes((0x83 if n < 0 else 0x84,)) + u16(n)


def read(address, final=True):
    if address < 0x2258:
        # The variable opcode indexes forward from $7E2258. A wrapped offset
        # crosses into bank $7F; low WRAM needs an absolute dereference.
        return b'\x04' + u16(address) + bytes((0xD5 if final else 0x55,))
    return bytes((0x89 if final else 0x09,)) + u16((address - 0x2258) & 0xFFFF)


def continuing(value):
    # Single instructions terminate on their opcode, compound expressions on
    # their final operator. Never clear an operand byte or leave a dereference
    # terminated inside a comparison (the VM would execute its tail as script).
    if value[0] & 0x80:
        return bytes((value[0] & 0x7F,)) + value[1:]
    return value[:-1] + bytes((value[-1] & 0x7F,))


def expr(left, op, right):
    return continuing(left) + b'\x29' + continuing(right) + bytes((op | 0x80,))


def write(address, value):
    return b'\x18' + u16((address - 0x2258) & 0xFFFF) + value


def actor_pointer(variable, field, final=True):
    return read(variable, False) + b'\x29' + b'\x04' + u16(field) + bytes((0x9A if final else 0x1A,))


def actor_read(variable, field):
    return actor_pointer(variable, field, False) + b'\xD5'


def actor_write(variable, field, value):
    return b'\x7A' + actor_pointer(variable, field) + value


class Script:
    def __init__(self):
        self.data = bytearray()
        self.labels = {}
        self.fixups = []

    def emit(self, data):
        self.data.extend(data)

    def label(self, name):
        self.labels[name] = len(self.data)

    def branch(self, expression, label, truth=True):
        self.emit(bytes((8 if truth else 9,)) + expression)
        self.fixups.append((len(self.data), label))
        self.emit(b'\0\0')

    def jump(self, label):
        self.emit(b'\x04')
        self.fixups.append((len(self.data), label))
        self.emit(b'\0\0')

    def finish(self):
        for at, label in self.fixups:
            struct.pack_into('<h', self.data, at, self.labels[label] - at - 2)
        return bytes(self.data)


def text_hook():
    # Native text resolver entry: 16-bit A/X, A=text ID. Preserve entry status
    # on the vanilla path; reproduce STA $26 / LDA #$F5 before continuing.
    c = Asm(TEXT_HOOK)
    c.emit('08 48 c9 f9 ff')
    c.when(0xD0, 'vanilla')
    c.emit('af e0 28 7e c9 47 4d')
    c.when(0xD0, 'vanilla')
    c.emit('af e2 28 7e c9 01 00')
    c.when(0xD0, 'vanilla')
    c.emit('af e6 28 7e c9 02 00')
    c.when(0xD0, 'vanilla')
    c.emit('68 28 a9 00 f0 85 22 a9 7f 00 85 24 6b')
    c.label('vanilla')
    c.emit('68 28 85 26 a9 f5 00 5c fa cc 8c')
    return c.finish()


def teleport(variable, x, y):
    return b'\x43' + read(variable) + x + y


def initialize_actor(s, variable, hp):
    s.emit(write(variable, b'\xAD'))
    s.emit(b'\x2A' + read(variable))
    for field, value in ((0x66, 0), (0x68, 0), (0x2A, hp)):
        s.emit(actor_write(variable, field, const(value)))
    s.emit(b'\x78' + read(variable) + u16(0x8000) + b'\xB0')


def interpolate(start, target, steps):
    # Weighted positive coordinates avoid the VM's unsigned division of a
    # negative delta (which can otherwise teleport an actor outside the arena).
    remaining = expr(const(steps), 0x1B, read(STEP))
    origin = expr(const(start), 0x17, remaining)
    destination = expr(read(target), 0x17, read(STEP))
    return expr(expr(origin, 0x1A, destination), 0x18, const(steps))


def hit(s, x, y, radius, damage, label):
    # Scripted hit uses the engine's damage animation and normal game-over path.
    # Check both axes so moving away from the telegraphed target avoids damage.
    for position, target in ((0x4EA3, x), (0x4EA5, y)):
        difference = expr(read(position), 0x1B, target)
        s.branch(expr(difference, 0x1E, const(-radius)), label)
        s.branch(expr(difference, 0x1F, const(radius)), label)
    s.emit(b'\x92\xD0' + const(damage))
    s.label(label)


def encounter_script(source, packed_script):
    s = Script()
    s.emit(write(MAILBOX, const(MAGIC)))
    s.emit(write(MAILBOX + 2, const(VERSION)))
    s.emit(write(REQUEST, expr(read(REQUEST), 0x1A, const(1))))
    s.emit(write(STATUS, const(1)))
    s.emit(write(ELAPSED, const(0)))
    s.emit(write(CHOICE, const(0xFFFF)))
    for variable in (CLAW1, CLAW2, PROJECTILE):
        s.emit(write(variable, const(0)))
    s.label('wait')
    s.branch(expr(read(STATUS), 0x22, const(2)), 'speak')
    s.branch(expr(read(ELAPSED), 0x21, const(600)), 'fallback')
    s.emit(b'\x3A' + write(ELAPSED, expr(read(ELAPSED), 0x1A, const(1))))
    s.jump('wait')
    s.label('fallback')
    s.emit(write(STATUS, const(3)))
    s.label('speak')
    s.emit(bytes.fromhex('a3 02 51') + u16(DYNAMIC_TEXT) + b'\x55')
    s.label('choose')
    s.emit(bytes.fromhex('a3 02 51') + u16(MENU_TEXT))
    s.emit(write(CHOICE, b'\x30\xAC') + b'\x55')
    s.branch(expr(read(CHOICE), 0x21, const(3)), 'choose')
    s.emit(write(STATUS, const(4)))
    # Straight-line original camera/pose setup; all embedded calls are absolute.
    s.emit(source[0x1BC4DD:0x1BC509])
    # Original bosses reserve sprite palettes used by bystanders. Let the
    # opening cowboy leave before combat instead of recoloring his artwork.
    s.branch(expr(actor_read(0x0341, 0x66), 0x22, const(0x19AA)), 'bystander_left', truth=False)
    s.emit(b'\x9B' + read(0x0341))
    s.label('bystander_left')
    s.branch(expr(read(CHOICE), 0x22, const(0)), 'thraxx')
    s.branch(expr(read(CHOICE), 0x22, const(1)), 'salabog')
    s.emit(b'\xBA\x35\x3E\x24')
    s.jump('spawned')
    s.label('salabog')
    s.emit(b'\xBA\x2C\x3E\x24')
    s.jump('spawned')
    s.label('thraxx')
    for template, variable, x in ((0x10, CLAW1, 57), (0x11, CLAW2, 67)):
        s.emit(bytes((0xBA, template, x, 38)))
        initialize_actor(s, variable, 32767)
        s.emit(b'\x78' + read(variable) + u16(0x8008) + b'\xB0')
    s.emit(b'\xBA\x14\x3E\x24')
    s.label('spawned')
    initialize_actor(s, BOSS, 600)
    # Station balance is local to these instances; original definitions remain.
    for field in (0x32, 0x34, 0x36):
        s.emit(actor_write(BOSS, field, const(0)))
    s.emit(b'\xBD')
    s.label('fight')
    s.branch(expr(actor_read(BOSS, 0x2A), 0x20, const(0)), 'victory')
    s.emit(b'\xA7\x59')  # 90 ticks between attacks; native delay is N+1.
    s.branch(expr(actor_read(BOSS, 0x2A), 0x20, const(0)), 'victory')
    s.emit(write(TARGET_X, read(0x4EA3)) + write(TARGET_Y, read(0x4EA5)))
    s.emit(write(STEP, const(0)))
    s.branch(expr(read(CHOICE), 0x22, const(0)), 'claws')
    s.branch(expr(read(CHOICE), 0x22, const(1)), 'fire')
    # Magmar: jump toward the last observed position, then slam with a quake.
    s.label('jump')
    s.emit(write(STEP, expr(read(STEP), 0x1A, const(1))))
    s.branch(expr(read(STEP), 0x1F, const(16)), 'descending')
    height = expr(read(STEP), 0x17, const(4))
    s.emit(teleport(BOSS, interpolate(496, TARGET_X, 32),
                    expr(interpolate(288, TARGET_Y, 32), 0x1B, height)))
    s.jump('jump_tick')
    s.label('descending')
    height = expr(expr(const(32), 0x1B, read(STEP)), 0x17, const(4))
    s.emit(teleport(BOSS, interpolate(496, TARGET_X, 32),
                    expr(interpolate(288, TARGET_Y, 32), 0x1B, height)))
    s.label('jump_tick')
    s.emit(b'\x3A')
    s.branch(expr(read(STEP), 0x1E, const(32)), 'jump')
    s.emit(b'\x8D\x01')
    hit(s, read(TARGET_X), read(TARGET_Y), 28, 5, 'slam_miss')
    s.emit(b'\xA7\x09\x8D\x00\xA7\x1D')
    s.emit(teleport(BOSS, const(496), const(288)))
    s.jump('fight')
    # Salabog: original fire-effect graphics follow a visible aimed projectile.
    s.label('fire')
    s.emit(b'\xBA\x20\x3E\x24')
    initialize_actor(s, PROJECTILE, 32767)
    s.emit(b'\x78' + read(PROJECTILE) + u16(0x0132) + b'\xB4')
    s.label('fire_tick')
    s.emit(write(STEP, expr(read(STEP), 0x1A, const(1))))
    s.emit(teleport(PROJECTILE, interpolate(496, TARGET_X, 32),
                    interpolate(288, TARGET_Y, 32)))
    s.emit(b'\x3A')
    s.branch(expr(read(STEP), 0x1E, const(32)), 'fire_tick')
    hit(s, read(TARGET_X), read(TARGET_Y), 18, 4, 'fire_miss')
    s.emit(b'\x9B' + read(PROJECTILE) + write(PROJECTILE, const(0)))
    s.jump('fight')
    # Thraxx: indestructible claws converge; the exposed heart is the target.
    s.label('claws')
    s.emit(write(STEP, expr(read(STEP), 0x1A, const(1))))
    for variable, x in ((CLAW1, 456), (CLAW2, 536)):
        s.emit(teleport(variable, interpolate(x, TARGET_X, 24),
                        interpolate(304, TARGET_Y, 24)))
    s.emit(b'\x3A')
    s.branch(expr(read(STEP), 0x1E, const(24)), 'claws')
    hit(s, read(TARGET_X), read(TARGET_Y), 20, 3, 'claws_miss')
    s.emit(b'\xA7\x0E')
    for variable, x in ((CLAW1, 456), (CLAW2, 536)):
        s.emit(teleport(variable, const(x), const(304)))
    s.jump('fight')
    s.label('victory')
    s.emit(write(STATUS, const(5)))
    s.emit(b'\xBC\x8D\x00')
    for variable in (BOSS, CLAW1, CLAW2, PROJECTILE):
        s.branch(expr(read(variable), 0x22, const(0)), f'clean_{variable}')
        s.emit(b'\x9B' + read(variable))
        s.emit(write(variable, const(0)))
        s.label(f'clean_{variable}')
    s.emit(write(0x2865, const(2)))
    s.emit(b'\x29' + u24(packed_script(0x1BC5E7)) + b'\x00')
    return s.finish()


def install(rom, source, layout, checked, packed_script, packed_text):
    def put(offset, data, name):
        end = offset + len(data)
        if end > len(rom) or any(offset < a['end'] and end > a['offset'] for a in layout['allocations']):
            raise ValueError(f'Gamemaster allocation overlap: {name}')
        checked(rom, offset, b'\xFF' * len(data), data)
        layout['allocations'].append({'name': name, 'offset': offset, 'end': end})

    # Redirect after the original Bazooka award. END prevents original robots
    # from spawning; later station visits use another branch of the chest event.
    hook = 0x1BC4DD
    checked(rom, hook, source[hook:hook + 5], b'\x29' + u24(packed_script(SCRIPT)) + b'\x00')
    put(0x33F000, b'EVERMORE-GM-0001', 'gamemaster bridge signature')
    put(SCRIPT, encounter_script(source, packed_script), 'gamemaster encounter')
    fallback = (b'\x96Gamemaster:\n\x81!\x86That name has\nhero potential!\x86\0')
    menu = b'\x96Which boss?\n\x8BThraxx\n\x8BSalabog\n\x8BMagmar\0'
    put(TEXT, fallback + menu, 'gamemaster fallback and menu')
    for text_id, offset in ((DYNAMIC_TEXT, TEXT), (MENU_TEXT, TEXT + len(fallback))):
        at = 0x350000 + text_id
        checked(rom, at, source[0x11D000 + text_id:0x11D003 + text_id], u24(packed_text(offset)))
    checked(rom, 0x0CCCF5, bytes.fromhex('85 26 a9 f5 00'), b'\x5C' + u24(0xC00000 + TEXT_HOOK) + b'\xEA')
    put(TEXT_HOOK, text_hook(), 'gamemaster RAM text resolver')
    layout['gamemaster'] = {'version': VERSION, 'bosses': list(BOSSES),
                            'mailbox': 0x7E0000 + MAILBOX,
                            'text_ram': TEXT_RAM, 'text_capacity': TEXT_CAPACITY,
                            'live_ai': 'Ollama through opt-in Luna bridge'}
