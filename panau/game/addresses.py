"""Every address and offset the overlay and cheats use, for the Steam build of JustCause2.exe (32-bit, image base
0x400000, no ASLR). All were found by disassembling the game's own code, mostly its Lua bindings and constructors.

build_ok() checks the code at a few of these sites before anything is read or written, so a different game version
is refused instead of being written to blindly.
"""

# --- build check: (address, expected bytes) of code that embeds the addresses below -------------------------------
SIGNATURES = [
    # GetAmmoInfo worker: push ebp; mov ebp,esp; sub esp,38; push ebx; push esi; mov esi,[0x118FB24]
    (0x00556250, bytes.fromhex('558bec83ec385356' '8b3524fb1801')),
    # CResourceItem constructor: add [0x1191748], edx (pickup count) ; cmp [0x119180C], ecx (pickup list head)
    (0x005AB77C, bytes.fromhex('011548171901' '390d0c181901')),
    # CTargetIndicator constructor: add dword [0x1191258], 1 (objective marker count)
    (0x006C4688, bytes.fromhex('830558121901' '01')),
    # IsBlackmarketActive worker: mov cl, [0x1197AC8] (black market open)
    (0x00747687, bytes.fromhex('8a0dc87a1901')),
    # GetTimeOfDay script function: mov ecx, [0x1191154]; movss xmm0, [ecx+20h]
    (0x00A2DCF8, bytes.fromhex('8b0d54111901' 'f30f104120')),
]

# --- player (CCharacterManager singleton -> CPlayer -> CCharacter) --------------------------------------------------
CHARACTER_MANAGER = 0x0118FB24        # [this] = CCharacterManager*
PLAYER = 0x3570                       # [manager + PLAYER] = CPlayer*
CHARACTER = 0x48                      # [player + CHARACTER] = CCharacter*
HEALTH_MAX, HEALTH = 0xE4, 0xE8       # floats on the character
INVENTORY = 0x484                     # [character + INVENTORY] = inventory
WEAPON_SLOT = 0x3C                    # weapon i = [inventory + 0x3C + 8*i], i < 16
RESERVE = 0x78                        # reserve ammo of type t = i32 [inventory + 0x78 + 4*t]
WEAPON_CLIP = 0x1E8                   # i32 rounds in the clip
WEAPON_DATA = 0x224                   # [weapon + 0x224] = weapon type data
AMMO_TYPE = 0x0C                      # i32 [data + 0x0C]
CLIP_SIZES = 0x354                    # float[6] [data + 0x354]: clip size per upgrade level
WEAPON_UPGRADE = 0xE00                # [weapon + 0xE00] -> upgrade info: byte +0x1A set = level 5, else byte +0x1B

# --- render camera ----------------------------------------------------------------------------------------------------
CAMERA = 0x01382050                   # [this] = the active NGraphicsEngine::CCamera
CAMERA_MATRIX = 0x24                  # 4x4 floats: rows right, up, back, position (right-handed, looks along -back)
CAMERA_PROJECTION = 0x64              # 4x4 floats: [0] = x scale, [5] = y scale

# --- loaded pickups (CResourceItem): an intrusive list ------------------------------------------------------------------
PICKUP_HEAD, PICKUP_VTABLE = 0x0119180C, 0x00EBD42C
PICKUP_NEXT, PICKUP_GROUP, PICKUP_COLLECTED = 0x40, 0x28, 0x44     # byte +0x44 = 1 the moment it is picked up

# --- loaded objective markers (CTargetIndicator): an intrusive list ----------------------------------------------------
MARKER_HEAD, MARKER_VTABLE = 0x011910A0, 0x00EB8FA4
MARKER_NEXT, MARKER_GROUP, MARKER_STATUS, MARKER_TYPE, MARKER_POS = 0x40, 0x28, 0x4C, 0x50, 0xB4
MARKER_SABOTAGE = 0x11                # status bit 0 = standing; it clears the instant the target is destroyed
MARKER_PANEL = 0x15                   # interaction marker; a pipeline control panel's status bit 0 = still standing
MARKER_ITEMS = {0x01: 'weapon part', 0x02: 'vehicle part', 0x0C: 'cash', 0x1D: 'armor'}

# --- menus (see overlay.Overlay.in_menu) ---------------------------------------------------------------------------------
# The pause menu and the map pause the world, so the time of day stops; the pause menu also shows a mouse cursor. The
# black market does neither, but the game keeps a flag for it: the byte its IsBlackmarketActive script function returns.
BLACK_MARKET_OPEN = 0x01197AC8
TIME_OF_DAY = 0x01191154, 0x20        # float hours at [this] + 0x20, what the GetTimeOfDay script function returns

# --- the in-memory progress table (same layout as the save's world section) ---------------------------------------------
WORLD_BITS_OFFSET = 190672            # the bit array follows the 23,833 x 8-byte keys at this distance


def build_ok(game):
    """True if the running exe has the expected code at every signature site."""
    return all(game.read(addr, len(sig)) == sig for addr, sig in SIGNATURES)
