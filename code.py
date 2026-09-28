"""
cloud_controller_v7.py  --  Maya Python scripting, example #7

Now it's a GAME. You have a time limit (90 seconds to start with; change it with the
"Game time" slider) to grow as many flowers as you can.

    * Press "Start Game". A countdown runs across the top of the window.
    * Every flower that finishes growing is COLLECTED: it scores one point, and the
      point can't be lost, even if that flower withers later.
    * Sun flowers need sunlight, rain flowers need rain. A yellow glow or blue
      bubbles mean "help me". A flower that starves withers fast and never scores.
    * When time runs out the garden freezes and the banner shows your score.
      Press "Play Again" to try to beat it.

The garden rules are the same as example #6:
    * The cloud moves horizontally (Left / Right / Forward / Back).
    * Sun flowers grow only outside the cloud's shadow.
      Rain flowers grow only while it is raining on them.
    * A need that stays unmet for NEED_PATIENCE_SECONDS makes a flower starve and wither fast.
    * Grown-up flowers age slowly (faster in the rain for sun flowers), then disappear,
      freeing their spot for new sprouts.

How to run:
    1. Open Maya's Script Editor (Windows > General Editors > Script Editor)
    2. Make a Python tab, paste this whole file, and press Ctrl+Enter.

New concepts compared to example #6:
    - Game states ("ready", "playing", "over") that decide which parts of the live
      update are allowed to run. Freezing the garden is just "skip the update".
    - A countdown timer, and capping the last time step so a round lasts exactly
      as long as the "Game time" slider said when the round started.
    - A score that counts an event once (a flag on each flower stops double counting).
    - A banner whose text and colour change with the game state.
    - ONE-STEP UNDO: everything a button click builds is wrapped in an undo chunk,
      so one click = one Ctrl+Z. If Undo takes the garden away, the game notices and stops.
    - CTRL+Z = BACK TO THE START: pressing Ctrl+Z during or after a round throws
      the round away and returns to the "Press Start Game" screen. It works
      whether the keyboard focus is in this window (a Qt shortcut) or in Maya's
      viewport (Maya's "Undo" event). The game's own edits (the live update, the
      cloud controls) are never put in Maya's Undo list, so they can't clash with it.
    - ONE GROUP: everything the script creates lives inside a single group
      (cloudGame_GRP), so the "Delete" button can remove it all with one delete
      (plus the materials it made), also in one Undo step.
"""

import math
import random
import time
from contextlib import contextmanager
from functools import partial

import maya.cmds as cmds


# --------------------------------------------------------------------------
# Settings (change these to experiment)
# --------------------------------------------------------------------------

# --- Names of things in the scene ---
ROOT_GROUP = "cloudGame_GRP"       # EVERYTHING the script creates is inside this one group
CLOUD_GROUP = "cloud_GRP"
FLOWERS_GROUP = "flowers_GRP"      # every flower lives inside this one group
GROUND = "ground_GEO"
SHADOW = "cloudShadow_GEO"
RAIN_GROUP = "rain_GRP"
WINDOW_ID = "cloudControllerWin"

# --- Ground ---
GROUND_SIZE = 40.0                 # the ground is a square, this wide and long
GROUND_Y = 0.0

# --- Cloud (it only moves left/right/forward/back, never up or down) ---
CLOUD_HEIGHT = 10.0
START_POSITION = (-12.0, CLOUD_HEIGHT, 0.0)   # starts to the left, NOT over the first flower
DEFAULT_STEP = 2.0                 # how far one key press moves the cloud

# Each "puff" is (x offset, y offset, z offset, radius).
PUFFS = [
    (0.0,  0.0,  0.0, 3.0),   # big middle puff
    (-3.0, -0.5, 0.5, 2.3),
    (3.2, -0.4, -0.3, 2.5),
    (-1.5, 1.6,  0.0, 2.2),
    (1.6,  1.8,  0.4, 2.0),
    (0.0, -0.8,  2.0, 2.0),
    (-5.2, -1.0, 0.0, 1.5),   # small puffs on the ends
    (5.4, -1.0,  0.2, 1.6),
]

# --- Sunlight and shadow ---
# The sun is straight overhead, so the cloud's shadow is an ellipse on the
# ground directly under the cloud. A flower inside it gets no sun.
SHADOW_RADIUS_X = 6.5
SHADOW_RADIUS_Z = 3.5
SHADOW_HEIGHT = 0.03               # sits just above the ground (avoids flicker)

# --- Flowers: growing ---
FIRST_FLOWER_POSITION = (0.0, 0.0)  # (x, z) of the very first flower
FIRST_FLOWER_NEED = "sun"          # the first flower is a sun flower ("sun" or "rain")
RAIN_LOVER_CHANCE = 0.5            # chance that a NEW sprout is a rain flower (0.0 to 1.0)
MAX_STEM_HEIGHT = 6.0
BLOOM_SIZE = 0.8                   # overall size of a finished flower head
PETAL_COUNT = 8
LEAF_ATTACH = (0.35, 0.6)          # how far up the stem each leaf grows (0 to 1)
LEAF_TILT_DEGREES = 20             # a fresh leaf tips up by this much
DEFAULT_GROW_SECONDS = 12.0        # seconds for a SUN flower to grow in full sunlight
RAIN_GROWTH_BOOST = 6.0            # a RAIN flower grows this many times faster (while it is raining on it)

# --- Flowers: needs ---
NEED_PATIENCE_SECONDS = 15.0       # a flower can go this long without its need before it starves
NEGLECT_RECOVERY = 2.0             # the neglect timer drains this many times faster than it fills
NEGLECT_WITHER_BOOST = 8.0         # a starving flower withers this many times faster

# --- Flowers: withering ---
DEFAULT_WITHER_SECONDS = 30.0      # seconds for a grown-up flower to wither away (normal ageing)
RAIN_WITHER_BOOST = 5.0            # a grown-up SUN flower in the rain ages this many times faster
LEAN_DEGREES = 30                  # the stem leans over this far when fully withered
HEAD_DROOP_DEGREES = 110           # the flower head hangs down this much MORE than the stem
LEAF_DROOP_DEGREES = 65            # leaves sag by this much
LEAF_SHRINK = 0.5                  # leaves shrink by this fraction when fully withered
PETAL_SHRINK = 0.45                # the flower head shrinks by this fraction
COLLAPSE_START = 0.85              # the flower sinks into the ground after this much wither
WITHER_STAGES = 5                  # number of colour steps from fresh to dead brown

# Colours: (fresh colour, dead colour, glow when fresh)
FLOWER_COLORS = {
    "plant":        ((0.15, 0.55, 0.15), (0.36, 0.26, 0.12), 0.0),
    "petal":        ((1.00, 0.45, 0.65), (0.32, 0.20, 0.12), 0.15),
    "flowerCenter": ((1.00, 0.85, 0.10), (0.22, 0.14, 0.05), 0.15),
}

# --- Signals: what a flower shows while its need is unmet ---
HALO_SIZE = 1.9                    # radius of the yellow glow around a full-grown flower head
HALO_PULSE = 0.15                  # how much the glow pulses in and out (0.15 = 15 percent)
HALO_PERIOD = 1.4                  # seconds for one pulse
BUBBLE_COUNT = 6                   # blue bubbles per rain flower
BUBBLE_SIZE = 0.28                 # biggest size of a bubble
BUBBLE_RADIUS = 1.0                # how far around the flower head the bubbles drift
BUBBLE_START_Y = -0.3              # bubbles start this far above (+) / below (-) the flower head
BUBBLE_RISE = 3.0                  # how high a bubble floats before it pops
BUBBLE_PERIOD = 2.4                # seconds for a bubble to rise and pop
BUBBLE_SWIRLS = 1.0                # how many times a bubble circles the flower as it rises

# --- Sprouting new flowers ---
MAX_FLOWERS = 12                   # the garden never gets bigger than this
SPAWN_AT = (0.4, 0.7, 1.0)         # a flower sprouts a new one at each of these growth levels
SPROUT_MIN_DISTANCE = 3.2          # new flowers appear this far from their parent...
SPROUT_MAX_DISTANCE = 6.5          # ...up to this far
MIN_FLOWER_GAP = 2.8               # never sprout closer than this to another flower
RANDOM_SEED = None                 # set to a number (e.g. 4) for the same garden every time

# --- Rain ---
RAIN_DROPS = 60                    # how many drops exist (they get reused)
RAIN_SPEED = 14.0                  # units per second
RAIN_SPAWN_RATE = 3.0              # how often a resting drop restarts (per second)
RAIN_RADIUS_X = 5.0                # rain falls (and soaks flowers) inside this ellipse
RAIN_RADIUS_Z = 2.6
CLOUD_BOTTOM_OFFSET = -2.2         # underside of the cloud, relative to its centre

# --- Simulation timing ---
TICK_MIN_DT = 0.04                 # ignore updates closer together than this (secs)
TICK_MAX_DT = 0.25                 # cap huge jumps (e.g. after a slow redraw)

# --- The game ---
GAME_SECONDS = 90.0                # starting value of the "Game time" slider (seconds per round)
MIN_GAME_SECONDS = 10.0            # the slider's range
MAX_GAME_SECONDS = 300.0
WARN_SECONDS = 30.0                # the banner turns orange when this much time is left...
DANGER_SECONDS = 10.0              # ...and red when this much is left (both shrink for short rounds)
BANNER_COLORS = {
    "ready":   (0.25, 0.35, 0.50),
    "playing": (0.20, 0.50, 0.25),
    "warn":    (0.75, 0.50, 0.10),
    "danger":  (0.75, 0.20, 0.15),
    "over":    (0.80, 0.65, 0.10),
}

# --- Names of the controls (we look them up by name later) ---
SLIDER_X = "cloudSliderX"
SLIDER_Z = "cloudSliderZ"
STEP_SLIDER = "cloudStepSlider"
GROW_SLIDER = "cloudGrowSlider"
WITHER_SLIDER = "cloudWitherSlider"
GAME_SLIDER = "cloudGameSlider"
STATUS_TEXT = "cloudStatusText"
NEEDS_TEXT = "cloudNeedsText"
LIFE_TEXT = "cloudLifeText"
HEALTH_BAR = "cloudHealthBar"
RAIN_BUTTON = "cloudRainButton"
START_BUTTON = "cloudStartButton"
DELETE_BUTTON = "cloudDeleteButton"
BANNER_TEXT = "cloudBannerText"
TIME_BAR = "cloudTimeBar"


# --------------------------------------------------------------------------
# The simulation's memory
# --------------------------------------------------------------------------

STATE = {
    "phase": "ready",    # "ready" (before the game), "playing", or "over" (time is up)
    "score": 0,          # flowers collected this round
    "game_seconds": GAME_SECONDS,   # length of the current / next round (from the slider)
    "time_left": GAME_SECONDS,   # seconds left in this round
    "banner": None,      # last banner (text, colour, percent) we showed
    "raining": False,
    "last_time": None,   # when we last updated (seconds)
    "time": 0.0,         # a running clock (seconds), used to animate glow and bubbles
    "ui": None,          # last text/percent we showed, so we only redraw on change
    "next_index": 1,     # the number the next flower will get in its name
    "died": 0,           # how many flowers have withered away so far
    "build_id": 0,       # which build of the scene this is (goes up every time we rebuild)
    "revert": False,     # an Undo happened during a round: tick() must go back to "ready"
    "chunk_depth": 0,    # > 0 while an undo chunk is open (tick() must not run then)
}

SHORTCUTS = []           # keeps the Qt shortcut objects alive (otherwise they are garbage collected)


# Names of every material the script has made (materials are not inside the
# group, so we keep a list to be able to delete them too).
MATERIALS = []


class Flower(object):
    """Everything we need to remember about ONE flower."""

    def __init__(self, index, x, z, height, need):
        self.index = index
        self.x = x                 # where it stands on the ground
        self.z = z
        self.height = height       # how tall its stem gets when fully grown
        self.need = need           # "sun" or "rain": what it needs to grow and stay healthy
        self.growth = 0.0          # 0.0 = seed, 1.0 = fully grown
        self.wither = 0.0          # 0.0 = fresh, 1.0 = fully withered (then it is removed)
        self.neglect = 0.0         # seconds its need has been unmet (drains when it is met)
        self.stage = 0             # which colour step it is showing (0 = fresh)
        self.spawned = 0           # how many new flowers this one has sprouted so far
        self.collected = False     # has it been counted in the score yet? (only ever once)
        self.signal_on = False     # is the glow / bubble effect showing right now?
        self.head = (0.0, height * 0.05, 0.0)   # where the top of the stem is (flower-local)

        # Each flower gets its own numbered node names, e.g. flower3_GRP.
        prefix = "flower{}".format(index)
        self.group = prefix + "_GRP"
        self.stem = prefix + "Stem_GEO"
        self.leaves = [prefix + "Leaf1_GRP", prefix + "Leaf2_GRP"]
        self.bloom = prefix + "Bloom_GRP"
        self.signal_group = prefix + "Signal_GRP"

        # Filled in when the flower is built (needed to recolour / animate it).
        self.leaf_shapes = []
        self.plant_parts = []      # stem + leaves
        self.petals = []
        self.center = None
        self.halo = None           # the yellow glow (sun flowers only)
        self.bubbles = []          # the blue bubbles (rain flowers only)


class Drop(object):
    """One raindrop: which Maya object it is, and where it is right now."""

    def __init__(self, name):
        self.name = name
        self.alive = False       # False = resting (hidden), True = falling
        self.x = self.y = self.z = 0.0


FLOWERS = []   # every living Flower in the garden
DROPS = []     # every raindrop


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

@contextmanager
def _one_undo_step():
    """Everything done inside a 'with _one_undo_step():' block is ONE Undo step.

    undoInfo(openChunk=True) starts grouping Maya's undo entries and
    undoInfo(closeChunk=True) ends the group. 'finally' guarantees the chunk is
    closed even if something inside fails; a chunk left open would swallow
    every later action the user does into the same Undo step.
    """
    STATE["chunk_depth"] += 1
    cmds.undoInfo(openChunk=True)
    try:
        yield
    finally:
        try:
            cmds.undoInfo(closeChunk=True)
        finally:
            STATE["chunk_depth"] -= 1


def _heal_undo(blind=False):
    """Get Undo working again if it is stuck.

    If a chunk is opened and never closed (or Undo is left switched off), Maya
    answers every Ctrl+Z with "Undo is temporarily unavailable. Try exiting the
    current tool." A stuck chunk stays stuck until it is closed, even after the
    script that opened it has been replaced, so we close any stray chunk here.
    (If this Maya cannot tell us how many chunks are open, we only guess when
    blind=True, which is used once, when the script starts.)
    """
    try:
        opened = int(cmds.undoInfo(query=True, openChunks=True) or 0)
    except Exception:
        opened = 1 if blind else 0
    try:
        for _ in range(min(opened, 20)):
            cmds.undoInfo(closeChunk=True)
    except Exception:
        pass
    STATE["chunk_depth"] = 0
    if not cmds.undoInfo(query=True, state=True):
        cmds.undoInfo(stateWithoutFlush=True)
        cmds.warning("Undo was switched off, so it has been switched back on.")


@contextmanager
def _suspend_undo():
    """Inside a 'with _suspend_undo():' block, scene edits are NOT put in the Undo list.

    Used for everything the GAME does by itself (the live update, moving the
    cloud, the rain tint). Only real builds ("Start Game", "Delete") belong in
    Undo. 'stateWithoutFlush' turns recording off WITHOUT clearing the old list.
    """
    was_on = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        yield
    finally:
        cmds.undoInfo(stateWithoutFlush=was_on)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _in_ellipse(px, pz, cx, cz, radius_x, radius_z):
    """Is the point (px, pz) inside the ellipse centred on (cx, cz)?

    (dx / rx)^2 + (dz / rz)^2  <=  1   means "inside".
    """
    dx = (px - cx) / radius_x
    dz = (pz - cz) / radius_z
    return dx * dx + dz * dz <= 1.0


def _make_material(name, rgb, glow=0.0, transparency=0.0):
    """Make a simple lambert shader called <name>_MAT (with a <name>_SG group).

    If one with that name already exists (from an earlier run) it is deleted
    first, so re-running the script never piles up extra materials.
    """
    material = name + "_MAT"
    shading_group = name + "_SG"
    if name not in MATERIALS:
        MATERIALS.append(name)         # remember it, so 'Delete' can clean it up later
    for node in (material, shading_group):
        if cmds.objExists(node):
            cmds.delete(node)

    material = cmds.shadingNode("lambert", asShader=True, name=material)
    cmds.setAttr(material + ".color", rgb[0], rgb[1], rgb[2], type="double3")
    cmds.setAttr(material + ".incandescence", glow, glow, glow, type="double3")
    if transparency:
        cmds.setAttr(
            material + ".transparency",
            transparency, transparency, transparency,
            type="double3",
        )

    # A shader must live in a "shading group" (a set) before it can be assigned.
    shading_group = cmds.sets(
        renderable=True, noSurfaceShader=True, empty=True, name=shading_group
    )
    cmds.connectAttr(material + ".outColor", shading_group + ".surfaceShader", force=True)


def _assign_material(objects, name):
    """Give objects an existing material (made earlier with _make_material)."""
    cmds.sets(objects, edit=True, forceElement=name + "_SG")


def _shade(objects, name, rgb, glow=0.0, transparency=0.0):
    """Make a material and assign it in one go (for things we only build once)."""
    _make_material(name, rgb, glow, transparency)
    _assign_material(objects, name)


def _stage_material(name, stage):
    """Name of the material for a colour stage, e.g. 'petal_w2'."""
    return "{}_w{}".format(name, stage)


def _set_visible(node, visible):
    cmds.setAttr(node + ".visibility", bool(visible))


def _cloud_position():
    return cmds.xform(CLOUD_GROUP, query=True, translation=True, worldSpace=True)


def _format_clock(seconds):
    """Turn seconds into m:ss, rounding UP so the display only shows 0:00 at time up."""
    whole = int(math.ceil(max(0.0, seconds) - 1e-6))   # (the tiny 1e-6 hides float rounding noise)
    minutes, secs = divmod(whole, 60)
    return "{}:{:02d}".format(minutes, secs)


def _random_need():
    """Pick a need for a new sprout: rain with chance RAIN_LOVER_CHANCE, otherwise sun."""
    return "rain" if random.random() < RAIN_LOVER_CHANCE else "sun"


# --------------------------------------------------------------------------
# Step 1: build the scene
# --------------------------------------------------------------------------

def create_cloud():
    """Create the cloud geometry, shade it white, and group it."""
    puffs = []
    for i, (x, y, z, radius) in enumerate(PUFFS):
        sphere = cmds.polySphere(
            radius=radius,
            subdivisionsX=24,
            subdivisionsY=16,
            name="cloudPuff{}".format(i + 1),
        )[0]
        cmds.move(x, y, z, sphere, absolute=True)
        cmds.scale(1.0, 0.75, 1.0, sphere)  # flatten slightly
        puffs.append(sphere)

    group = cmds.group(puffs, name=CLOUD_GROUP)
    cmds.xform(group, worldSpace=True, pivots=(0, 0, 0))

    _shade(puffs, "cloud", (1.0, 1.0, 1.0), glow=0.3)
    cmds.xform(group, translation=START_POSITION, worldSpace=True)
    return group


def create_ground():
    """A big flat green plane for the flowers to grow on."""
    ground = cmds.polyPlane(
        width=GROUND_SIZE, height=GROUND_SIZE, subdivisionsX=1, subdivisionsY=1, name=GROUND
    )[0]
    _shade([ground], "ground", (0.25, 0.5, 0.18))
    return ground


def create_shadow():
    """A dark, see-through flat disc on the ground. Shows where the cloud shades."""
    shadow = cmds.polyCylinder(
        radius=1, height=0.05, subdivisionsX=32, subdivisionsY=1, name=SHADOW
    )[0]
    cmds.scale(SHADOW_RADIUS_X, 1.0, SHADOW_RADIUS_Z, shadow)
    _shade([shadow], "shadow", (0.0, 0.0, 0.0), transparency=0.55)
    cmds.move(START_POSITION[0], SHADOW_HEIGHT, START_POSITION[2], shadow, absolute=True)
    return shadow


def create_flower_materials():
    """Make the flower colours (and the glow / bubble looks) ONCE. Every flower shares them.

    For each part (stem/leaves, petals, centre) we make several materials that
    step from the fresh colour to the dead brown colour:

        plant_w0 (fresh green) ... plant_w4 (dead brown)

    A withering flower is simply re-assigned to the next material along.
    """
    for name, (fresh, dead, glow) in FLOWER_COLORS.items():
        for stage in range(WITHER_STAGES):
            t = stage / float(WITHER_STAGES - 1)            # 0.0 fresh ... 1.0 dead
            rgb = tuple(f + (d - f) * t for f, d in zip(fresh, dead))   # blend
            _make_material(_stage_material(name, stage), rgb, glow=glow * (1.0 - t))

    # See-through, self-lit materials for the signals.
    _make_material("sunGlow", (1.0, 0.9, 0.2), glow=0.9, transparency=0.6)
    _make_material("bubble", (0.5, 0.8, 1.0), glow=0.5, transparency=0.45)


def create_flower(x, z, height, need):
    """Build one flower at ground position (x, z) as a seed, and add it to FLOWERS.

    Each flower is made of nested groups:

        flower1_GRP
         |- flower1Stem_GEO        (a thin cylinder; we stretch its height)
         |- flower1Leaf1_GRP       (a group per leaf, so it can scale from its base)
         |    '- leaf shape
         |- flower1Leaf2_GRP
         |    '- leaf shape
         |- flower1Bloom_GRP       (the flower head, rides on top of the stem)
         |    |- petals
         |    '- centre
         '- flower1Signal_GRP      (a yellow glow for sun flowers, or blue bubbles
                                    for rain flowers. Hidden until the need is unmet)
    """
    # A counter that only goes up, so a new flower never reuses the name of one
    # that has been deleted.
    index = STATE["next_index"]
    STATE["next_index"] += 1

    flower = Flower(index, x, z, height, need)
    prefix = "flower{}".format(index)

    group = cmds.group(empty=True, name=flower.group)

    # --- Stem: a cylinder that stretches UP from the ground ------------------
    # Scaling always happens around an object's PIVOT. So for the stem to grow
    # upward, its pivot must sit at the bottom of the cylinder (y = 0).
    stem = cmds.polyCylinder(
        radius=0.12, height=1, subdivisionsX=10, subdivisionsY=1, name=flower.stem
    )[0]
    # Move the VERTICES up by half the height (not the whole object). The
    # cylinder now spans y = 0 to 1, while its pivot stays behind at y = 0.
    cmds.move(0, 0.5, 0, stem + ".vtx[*]", relative=True)
    # Belt and braces: make sure the pivot really is at the origin (the base).
    cmds.xform(stem, worldSpace=True, pivots=(0, 0, 0))
    cmds.parent(stem, group)

    # --- Leaves: each one is a flattened sphere inside its own group --------
    for i, leaf_group in enumerate(flower.leaves):
        leaf_holder = cmds.group(empty=True, name=leaf_group)
        leaf = cmds.polySphere(
            radius=1, subdivisionsX=12, subdivisionsY=8,
            name="{}Leaf{}_GEO".format(prefix, i + 1),
        )[0]
        cmds.scale(0.9, 0.12, 0.4, leaf)
        cmds.move(0.9, 0.1, 0, leaf, absolute=True)           # sticks out to one side
        cmds.rotate(0, 0, LEAF_TILT_DEGREES, leaf)            # tips upward a little
        cmds.parent(leaf, leaf_holder)
        cmds.parent(leaf_holder, group)
        # Second leaf points the opposite way from the first.
        cmds.setAttr(leaf_holder + ".rotateY", 20 + 180 * i)
        flower.leaf_shapes.append(leaf)

    # --- Bloom: petals in a ring around a yellow centre --------------------
    bloom = cmds.group(empty=True, name=flower.bloom)
    cmds.parent(bloom, group)

    for i in range(PETAL_COUNT):
        angle = i * 360.0 / PETAL_COUNT
        radians = math.radians(angle)
        petal = cmds.polySphere(
            radius=1, subdivisionsX=10, subdivisionsY=6,
            name="{}Petal{}_GEO".format(prefix, i + 1),
        )[0]
        cmds.scale(0.8, 0.18, 0.4, petal)
        # Place the petal on a circle, and turn it to point away from the centre.
        cmds.move(0.85 * math.cos(radians), 0.0, -0.85 * math.sin(radians), petal, absolute=True)
        cmds.rotate(0, angle, 0, petal)
        cmds.parent(petal, bloom)
        flower.petals.append(petal)

    center = cmds.polySphere(
        radius=0.55, subdivisionsX=14, subdivisionsY=10, name=prefix + "Center_GEO"
    )[0]
    cmds.scale(1.0, 0.6, 1.0, center)
    cmds.move(0, 0.12, 0, center, absolute=True)
    cmds.parent(center, bloom)
    flower.center = center

    # Remember which parts get which colour (we recolour them as it withers).
    flower.plant_parts = [stem] + flower.leaf_shapes
    _assign_material(flower.plant_parts, _stage_material("plant", 0))
    _assign_material(flower.petals, _stage_material("petal", 0))
    _assign_material([flower.center], _stage_material("flowerCenter", 0))

    # --- Signal: a yellow glow (sun flower) OR blue bubbles (rain flower) ----
    signal = cmds.group(empty=True, name=flower.signal_group)
    cmds.parent(signal, group)
    if need == "sun":
        halo = cmds.polySphere(
            radius=1, subdivisionsX=16, subdivisionsY=12, name=prefix + "Halo_GEO"
        )[0]
        cmds.parent(halo, signal)
        _assign_material([halo], "sunGlow")
        _set_visible(halo, False)
        flower.halo = halo
    else:
        for i in range(BUBBLE_COUNT):
            bubble = cmds.polySphere(
                radius=1, subdivisionsX=10, subdivisionsY=8,
                name="{}Bubble{}_GEO".format(prefix, i + 1),
            )[0]
            cmds.parent(bubble, signal)
            _set_visible(bubble, False)
            flower.bubbles.append(bubble)
        _assign_material(flower.bubbles, "bubble")

    # Put the flower in the flowers group and stand it on the ground. Each one
    # is turned a random way, so they don't all lean in the same direction.
    cmds.parent(group, FLOWERS_GROUP)
    cmds.xform(group, translation=(x, GROUND_Y, z), worldSpace=True)
    cmds.setAttr(group + ".rotateY", random.uniform(0.0, 360.0))

    FLOWERS.append(flower)
    apply_flower(flower)
    return flower


def remove_flower(flower):
    """Delete a flower from the scene and from our list (frees its spot)."""
    if cmds.objExists(flower.group):
        cmds.delete(flower.group)          # deletes everything inside it too (glow, bubbles...)
    if flower in FLOWERS:
        FLOWERS.remove(flower)
    STATE["died"] += 1


def create_rain_pool():
    """Make a fixed pool of raindrops (hidden until it rains) and reuse them."""
    del DROPS[:]
    rain_group = cmds.group(empty=True, name=RAIN_GROUP)
    objects = []
    for i in range(RAIN_DROPS):
        drop = cmds.polyCylinder(
            radius=0.05, height=0.8, subdivisionsX=6, subdivisionsY=1,
            name="rainDrop{}_GEO".format(i + 1),
        )[0]
        cmds.parent(drop, rain_group)
        _set_visible(drop, False)
        DROPS.append(Drop(drop))
        objects.append(drop)
    _shade(objects, "rain", (0.35, 0.6, 1.0), glow=0.3)


def create_scene():
    """Delete any old copy of the scene and build everything fresh."""
    for node in [ROOT_GROUP, CLOUD_GROUP, FLOWERS_GROUP, GROUND, SHADOW, RAIN_GROUP]:
        if cmds.objExists(node):
            cmds.delete(node)

    del FLOWERS[:]
    STATE["raining"] = False
    STATE["last_time"] = None
    STATE["time"] = 0.0
    STATE["ui"] = None
    STATE["next_index"] = 1
    STATE["died"] = 0
    STATE["score"] = 0
    STATE["game_seconds"] = _round_length()      # the "Game time" slider, read when a round is built
    STATE["time_left"] = STATE["game_seconds"]
    STATE["banner"] = None
    STATE["revert"] = False
    if RANDOM_SEED is not None:
        random.seed(RANDOM_SEED)

    create_ground()
    create_shadow()
    create_rain_pool()
    create_cloud()

    create_flower_materials()
    cmds.group(empty=True, name=FLOWERS_GROUP)

    # Put every piece inside ONE group. From now on, deleting ROOT_GROUP deletes
    # the whole game. (The new flowers that sprout later go into FLOWERS_GROUP,
    # which is already inside it.)
    root = cmds.group(empty=True, name=ROOT_GROUP)
    for node in (GROUND, SHADOW, RAIN_GROUP, CLOUD_GROUP, FLOWERS_GROUP):
        cmds.parent(node, root)

    # Stamp this build on the group. If the user presses Ctrl+Z, Maya may bring
    # back an OLDER garden; the stamp lets tick() see that it isn't ours anymore.
    STATE["build_id"] += 1
    cmds.addAttr(root, longName="buildId", attributeType="long")
    cmds.setAttr(root + ".buildId", STATE["build_id"])


def plant_first_flower():
    """Plant the first seed. Call it right after create_scene(), OUTSIDE the undo chunk.

    Flowers are born and die while the game runs, and the game's edits are not in
    the Undo list. If the first flower were part of the "Start Game" undo step, it
    could be gone (withered away) by the time you press Ctrl+Z, and Maya could not
    undo the step cleanly. Everything that is in the Undo step lives as long as
    the group does; the flowers inside it just get deleted along with the group.
    """
    fx, fz = FIRST_FLOWER_POSITION
    create_flower(fx, fz, MAX_STEM_HEIGHT, FIRST_FLOWER_NEED)


# --------------------------------------------------------------------------
# Step 2: how a flower LOOKS at a given growth and wither
# --------------------------------------------------------------------------

def apply_flower(flower):
    """Shape one flower to match its two numbers: growth and wither (each 0 to 1).

    Growing (wither = 0):
        growth 0.00 - 0.70   the stem stretches up
        growth 0.20 - 0.60   the leaves unfold
        growth 0.65 - 1.00   the flower head opens

    Withering (wither goes 0 -> 1):
        the stem leans over, the head hangs down, the leaves sag and shrink,
        the colours turn brown, and at the very end it sinks into the ground.
    """
    growth = flower.growth
    wither = flower.wither

    stem_t = _clamp(growth / 0.7)
    leaf_t = _clamp((growth - 0.2) / 0.4)
    bloom_t = _clamp((growth - 0.65) / 0.35)

    # Never let the stem be exactly zero tall (it would vanish completely).
    stem_height = flower.height * (0.05 + 0.95 * stem_t)

    # --- Stem: stretch it, and lean it over as it withers -------------------
    lean_degrees = LEAN_DEGREES * wither
    lean = math.radians(lean_degrees)

    def along_stem(distance):
        """Where is the point <distance> up the (leaning) stem? Leaning about the
        Z axis by 'lean' moves a point that was straight up to (-sin, cos)."""
        return (-math.sin(lean) * distance, math.cos(lean) * distance, 0.0)

    cmds.setAttr(flower.stem + ".scaleY", stem_height)
    cmds.setAttr(flower.stem + ".rotateZ", lean_degrees)

    # Remember where the top of the stem is: the glow and bubbles gather there.
    flower.head = along_stem(stem_height)

    # --- Leaves: ride along the stem, then sag and shrink -------------------
    leaf_size = leaf_t * (1.0 - LEAF_SHRINK * wither)
    for leaf_group, leaf_shape, attach in zip(flower.leaves, flower.leaf_shapes, LEAF_ATTACH):
        _set_visible(leaf_group, leaf_t > 0)
        if leaf_t > 0:
            lx, ly, lz = along_stem(stem_height * attach)
            cmds.setAttr(leaf_group + ".translate", lx, ly, lz, type="double3")
            cmds.setAttr(leaf_group + ".scale", leaf_size, leaf_size, leaf_size, type="double3")
            cmds.setAttr(leaf_shape + ".rotateZ", LEAF_TILT_DEGREES - LEAF_DROOP_DEGREES * wither)

    # --- Bloom: sits on the top of the stem, hangs its head, shrinks --------
    _set_visible(flower.bloom, bloom_t > 0)
    if bloom_t > 0:
        bx, by, bz = flower.head
        size = BLOOM_SIZE * bloom_t * (1.0 - PETAL_SHRINK * wither)
        cmds.setAttr(flower.bloom + ".translate", bx, by, bz, type="double3")
        cmds.setAttr(flower.bloom + ".scale", size, size, size, type="double3")
        # The head follows the stem's lean, then droops further on top of that.
        cmds.setAttr(flower.bloom + ".rotateZ", lean_degrees + HEAD_DROOP_DEGREES * wither)

    # --- Colour: switch to the next brown-er material when a step is reached
    stage = min(WITHER_STAGES - 1, int(wither * WITHER_STAGES))
    if stage != flower.stage:
        flower.stage = stage
        _assign_material(flower.plant_parts, _stage_material("plant", stage))
        _assign_material(flower.petals, _stage_material("petal", stage))
        _assign_material([flower.center], _stage_material("flowerCenter", stage))

    # --- The very end: the whole flower sinks into the ground --------------
    collapse = _clamp((wither - COLLAPSE_START) / (1.0 - COLLAPSE_START))
    s = 1.0 - collapse                     # 1.0 = normal size, 0.0 = sunk out of sight
    cmds.setAttr(flower.group + ".scale", s, s, s, type="double3")


# --------------------------------------------------------------------------
# Step 3: the signals (yellow glow / blue bubbles)
# --------------------------------------------------------------------------

def _set_signal_visible(flower, on):
    """Show or hide a flower's glow / bubbles (only touches Maya when it changes)."""
    if flower.signal_on == on:
        return
    flower.signal_on = on
    for node in ([flower.halo] if flower.halo else []) + flower.bubbles:
        _set_visible(node, on)


def _update_signal(flower, unmet):
    """Show the signal while the flower's need is unmet, and animate it.

    Everything here is placed in the flower's own space (the signal nodes are
    children of the flower), so it follows the flower's lean and gets deleted with it.
    """
    _set_signal_visible(flower, unmet)
    if not unmet:
        return

    t = STATE["time"]                       # running clock in seconds
    hx, hy, hz = flower.head                # top of the stem

    # Sun flower: a yellow glow around the flower head that pulses gently.
    if flower.halo:
        pulse = 1.0 + HALO_PULSE * math.sin(2.0 * math.pi * t / HALO_PERIOD + flower.index)
        size = HALO_SIZE * (0.35 + 0.65 * flower.growth) * pulse   # small seed, big glow when grown
        cmds.setAttr(flower.halo + ".translate", hx, hy, hz, type="double3")
        cmds.setAttr(flower.halo + ".scale", size, size, size, type="double3")

    # Rain flower: bubbles that swirl up around the head, then pop.
    spread = BUBBLE_RADIUS * (0.4 + 0.6 * flower.growth)
    for i, bubble in enumerate(flower.bubbles):
        # phase goes 0 -> 1 over each bubble's life; the bubbles are spaced out evenly.
        phase = (t / BUBBLE_PERIOD + i / float(BUBBLE_COUNT)) % 1.0
        angle = 2.0 * math.pi * (phase * BUBBLE_SWIRLS + i / float(BUBBLE_COUNT))
        bx = hx + spread * math.cos(angle)
        bz = hz + spread * math.sin(angle)
        by = hy + BUBBLE_START_Y + phase * BUBBLE_RISE
        size = max(0.02, BUBBLE_SIZE * math.sin(math.pi * phase))  # grows, then shrinks to a pop
        cmds.setAttr(bubble + ".translate", bx, by, bz, type="double3")
        cmds.setAttr(bubble + ".scale", size, size, size, type="double3")


# --------------------------------------------------------------------------
# Step 4: the live life cycle (needs, growth, starving, withering)
# --------------------------------------------------------------------------

def _update_flowers(dt):
    """Move every flower along its life cycle by a small step of time (dt).

    1. Is the flower's NEED met right now?
         sun flower:  met while it is NOT in the cloud's shadow
         rain flower: met while rain is falling on it
    2. The neglect timer: fills up while the need is unmet, drains while it is met.
       Once it passes NEED_PATIENCE_SECONDS the flower is STARVING.
    3. Growth: a flower only grows while its need is met
       (a rain flower grows RAIN_GROWTH_BOOST times faster than a sun flower).
       The moment a flower is fully grown it is COLLECTED (+1 point).
    4. Withering:
         grown up            ->  ages slowly (a sun flower ages faster in the rain)
         starving            ->  withers NEGLECT_WITHER_BOOST times faster on top
       When wither reaches 1 the flower is removed.
    5. The glow / bubbles show while the need is unmet.

    Returns a dictionary of counts for the status display.
    """
    cx, cy, cz = _cloud_position()
    raining = STATE["raining"]
    grow_seconds = max(cmds.floatSliderGrp(GROW_SLIDER, query=True, value=True), 0.1)
    wither_seconds = max(cmds.floatSliderGrp(WITHER_SLIDER, query=True, value=True), 0.1)

    counts = {"sun": 0, "sun_waiting": 0, "rain": 0, "rain_waiting": 0, "grown": 0, "starving": 0}

    # Loop over a COPY of the list, because remove_flower() changes the real one.
    for flower in list(FLOWERS):
        shaded = _in_ellipse(flower.x, flower.z, cx, cz, SHADOW_RADIUS_X, SHADOW_RADIUS_Z)
        watered = raining and _in_ellipse(flower.x, flower.z, cx, cz, RAIN_RADIUS_X, RAIN_RADIUS_Z)

        # ---- 1. is the need met? ----
        if flower.need == "sun":
            met = not shaded
        else:
            met = watered

        # ---- 2. the neglect timer ----
        if met:
            flower.neglect = max(0.0, flower.neglect - NEGLECT_RECOVERY * dt)
        else:
            flower.neglect += dt
        starving = flower.neglect >= NEED_PATIENCE_SECONDS

        changed = False

        # ---- 3. growth (only while the need is met) ----
        if flower.growth < 1.0 and met:
            speed = RAIN_GROWTH_BOOST if flower.need == "rain" else 1.0
            # speed * dt / grow_seconds = the slice of growth earned in this moment.
            flower.growth = min(1.0, flower.growth + speed * dt / grow_seconds)
            changed = True

        # ---- 3b. collect it: a fully grown flower scores ONE point, once ----
        if flower.growth >= 1.0 and not flower.collected and STATE["phase"] == "playing":
            flower.collected = True
            STATE["score"] += 1

        # ---- 4. withering ----
        wither_speed = 0.0
        if flower.growth >= 1.0:
            wither_speed = 1.0                           # normal ageing
            if watered and flower.need == "sun":
                wither_speed = RAIN_WITHER_BOOST         # rain speeds up ageing for sun flowers
        if starving:
            wither_speed += NEGLECT_WITHER_BOOST         # starving: withers fast
        if wither_speed > 0:
            flower.wither = min(1.0, flower.wither + wither_speed * dt / wither_seconds)
            changed = True
            if flower.wither >= 1.0:
                remove_flower(flower)                    # all the way withered: it's gone
                continue

        if changed:
            apply_flower(flower)

        # ---- 5. signals ----
        _update_signal(flower, unmet=not met)

        # ---- counts for the status display ----
        key = flower.need
        counts[key] += 1
        if not met:
            counts[key + "_waiting"] += 1
        if flower.growth >= 1.0:
            counts["grown"] += 1
        if starving:
            counts["starving"] += 1

    return counts


# --------------------------------------------------------------------------
# Step 5: new flowers sprout around growing ones
# --------------------------------------------------------------------------

def _find_sprout_spot(parent):
    """Pick a random spot around the parent flower that has room. None if no room."""
    limit = GROUND_SIZE / 2.0 - 2.0          # stay away from the edge of the ground

    for _ in range(40):                      # try a few random spots
        angle = random.uniform(0.0, 2.0 * math.pi)
        distance = random.uniform(SPROUT_MIN_DISTANCE, SPROUT_MAX_DISTANCE)
        x = parent.x + distance * math.cos(angle)
        z = parent.z + distance * math.sin(angle)

        if abs(x) > limit or abs(z) > limit:
            continue                         # off the ground
        if all(math.hypot(x - f.x, z - f.z) >= MIN_FLOWER_GAP for f in FLOWERS):
            return x, z                      # nobody is too close: this spot works
    return None


def _spawn_sprouts():
    """Each flower sprouts a new one every time its growth passes a SPAWN_AT level.

    Every new sprout gets a random need (sun or rain).
    If the garden is full, the sprout WAITS (it isn't used up). As soon as a
    withered flower disappears and frees a spot, the waiting sprout appears.
    """
    for flower in list(FLOWERS):             # a copy, because the list grows as we sprout
        while flower.spawned < len(SPAWN_AT) and flower.growth >= SPAWN_AT[flower.spawned]:
            if len(FLOWERS) >= MAX_FLOWERS:
                return                       # garden full: wait for a spot to open up
            flower.spawned += 1
            spot = _find_sprout_spot(flower)
            if spot:
                height = MAX_STEM_HEIGHT * random.uniform(0.7, 1.0)   # a bit of variety
                create_flower(spot[0], spot[1], height, _random_need())


# --------------------------------------------------------------------------
# Step 6: the shadow and the rain
# --------------------------------------------------------------------------

def _update_shadow():
    """Keep the dark disc on the ground directly under the cloud."""
    cx, cy, cz = _cloud_position()
    cmds.xform(SHADOW, translation=(cx, SHADOW_HEIGHT, cz), worldSpace=True)


def _update_rain(dt):
    """Move every falling drop, and start new drops while it is raining."""
    cx, cy, cz = _cloud_position()
    cloud_bottom = cy + CLOUD_BOTTOM_OFFSET

    for drop in DROPS:
        # 1. Falling drops move down. Drops that reach the ground go to rest.
        if drop.alive:
            drop.y -= RAIN_SPEED * dt
            if drop.y <= GROUND_Y:
                drop.alive = False
                _set_visible(drop.name, False)
            else:
                cmds.setAttr(drop.name + ".translate", drop.x, drop.y, drop.z, type="double3")

        # 2. While it is raining, resting drops restart from under the cloud.
        #    A random chance staggers the drops so the rain looks natural.
        if STATE["raining"] and not drop.alive and random.random() < RAIN_SPAWN_RATE * dt:
            angle = random.uniform(0.0, 2.0 * math.pi)
            radius = math.sqrt(random.random())   # sqrt spreads drops evenly, no clumping
            drop.x = cx + RAIN_RADIUS_X * radius * math.cos(angle)
            drop.z = cz + RAIN_RADIUS_Z * radius * math.sin(angle)
            drop.y = cloud_bottom
            drop.alive = True
            _set_visible(drop.name, True)
            cmds.setAttr(drop.name + ".translate", drop.x, drop.y, drop.z, type="double3")


def _tint_cloud():
    """Rain clouds are darker and greyer."""
    if STATE["raining"]:
        color, glow = (0.55, 0.58, 0.66), 0.1
    else:
        color, glow = (1.0, 1.0, 1.0), 0.3
    cmds.setAttr("cloud_MAT.color", color[0], color[1], color[2], type="double3")
    cmds.setAttr("cloud_MAT.incandescence", glow, glow, glow, type="double3")


# --------------------------------------------------------------------------
# Step 7: the live update (runs over and over while Maya is idle)
# --------------------------------------------------------------------------

def _scene_intact():
    """True if the scene is still the exact build the game is tracking."""
    if not (cmds.objExists(ROOT_GROUP) and cmds.objExists(CLOUD_GROUP) and cmds.objExists(FLOWERS_GROUP)):
        return False
    if cmds.getAttr(ROOT_GROUP + ".buildId") != STATE["build_id"]:
        return False                       # an older (or newer) garden came back
    tracked = [SHADOW, RAIN_GROUP] + [f.group for f in FLOWERS] + [d.name for d in DROPS]
    return all(cmds.objExists(node) for node in tracked)


def _scene_lost():
    """Undo took our garden away: stop the round and wait for 'Start Game'."""
    if STATE["phase"] == "ready":
        return
    STATE["phase"] = "ready"
    STATE["raining"] = False
    STATE["ui"] = None
    _show_stopped_status("The scene was changed (Undo).", "Press 'Start Game' to play again.")
    _refresh_rain_button()
    _refresh_start_button()
    _update_banner()


def _show_stopped_status(line1, line2):
    """Fill the three status lines with a message instead of garden numbers."""
    cmds.text(STATUS_TEXT, edit=True, label=line1)
    cmds.text(NEEDS_TEXT, edit=True, label=line2)
    cmds.text(LIFE_TEXT, edit=True, label="")
    cmds.progressBar(HEALTH_BAR, edit=True, progress=0)


def _revert_to_ready():
    """Ctrl+Z: throw this round away and go back to the state before 'Start Game'."""
    with _suspend_undo():
        create_scene()                    # a fresh, untouched garden
        plant_first_flower()
        STATE["phase"] = "ready"          # frozen until 'Start Game' is pressed
        _sync_sliders_to_cloud()
        _refresh_rain_button()
        _refresh_start_button()
        _show_garden_status()
        _update_banner()
    # The old Undo entries point at nodes we just replaced. Clear them, so a later
    # Undo or Redo can never touch a garden that no longer exists.
    cmds.flushUndo()


def _flush_stale_undo():
    """If a round was played, the older Undo entries are stale (the game edited
    those nodes without recording it). Clear them before making a new entry."""
    if STATE["phase"] != "ready":
        cmds.flushUndo()


def on_undo_event(*args):
    """Maya just did an Undo (keyboard focus in the viewport, Edit > Undo...).

    If a round is running or finished, ask tick() to go back to "ready". We only
    raise a flag here; editing the scene inside an Undo callback is asking for trouble.
    """
    if STATE["phase"] in ("playing", "over"):
        STATE["revert"] = True


def on_ctrl_z(*args):
    """Ctrl+Z pressed while the game window has the keyboard focus."""
    if STATE["phase"] in ("playing", "over"):
        _revert_to_ready()
    else:
        try:
            cmds.undo()                   # nothing running: an ordinary Maya undo
        except Exception:
            cmds.warning("Nothing to undo.")


def _install_undo_shortcut():
    """Make Ctrl+Z work while THIS window has the keyboard focus.

    Maya's own Ctrl+Z hotkey only works when the focus is in Maya's main window
    or a viewport. In a window made with cmds.window it does nothing, so we add
    the shortcut ourselves with Qt (PySide). Maya 2025+ uses PySide6, older uses PySide2.
    """
    try:
        from maya import OpenMayaUI
        try:
            from PySide6 import QtGui, QtWidgets
            from shiboken6 import wrapInstance
            QShortcut = QtGui.QShortcut
        except ImportError:
            from PySide2 import QtGui, QtWidgets
            from shiboken2 import wrapInstance
            QShortcut = QtWidgets.QShortcut
        pointer = OpenMayaUI.MQtUtil.findWindow(WINDOW_ID)
        window = wrapInstance(int(pointer), QtWidgets.QWidget)
        shortcut = QShortcut(QtGui.QKeySequence("Ctrl+Z"), window)
        shortcut.activated.connect(on_ctrl_z)
        SHORTCUTS.append(shortcut)
    except Exception as error:
        cmds.warning(
            "Ctrl+Z inside this window is not available ({}). "
            "Click in Maya's viewport first, then press Ctrl+Z.".format(error)
        )


def tick():
    """One live update. Maya calls this again and again through a scriptJob."""
    # Stop quietly if the window or the scene has been closed / cleared.
    if not cmds.window(WINDOW_ID, exists=True):
        return

    # Never touch the undo settings while an undo chunk is open (that can leave
    # the chunk stuck open, and then Maya refuses every Ctrl+Z).
    if STATE["chunk_depth"] > 0:
        return

    # An Undo happened during a round: go back to the state before 'Start Game'.
    if STATE["revert"]:
        STATE["revert"] = False
        _revert_to_ready()
        return

    if not (cmds.objExists(CLOUD_GROUP) and cmds.objExists(FLOWERS_GROUP)):
        return

    # How much real time passed since the last update? ("delta time")
    now = time.time()
    last = STATE["last_time"]
    if last is None:
        STATE["last_time"] = now
        return
    dt = now - last
    if dt < TICK_MIN_DT:
        return                    # too soon, wait for more time to add up
    STATE["last_time"] = now
    dt = min(dt, TICK_MAX_DT)     # don't let one slow moment cause a huge jump

    # Undo / Redo can remove or swap the garden behind our back. Never run the
    # game on a scene that isn't the one we built.
    if not _scene_intact():
        _scene_lost()
        return

    playing = STATE["phase"] == "playing"
    if playing:
        # Never step past the end of the round, so it lasts exactly as long as the slider said.
        dt = min(dt, STATE["time_left"])

    counts = None

    # These automatic updates should NOT fill up the user's Undo list.
    with _suspend_undo():
        _update_shadow()          # the cloud can always be moved, even before / after the game

        # The garden only runs while the game is being played. Before the game
        # and after time is up it is FROZEN, simply because we skip all of this.
        if playing:
            STATE["time"] += dt              # the running clock that animates glow and bubbles
            STATE["time_left"] -= dt         # the countdown
            counts = _update_flowers(dt)
            _spawn_sprouts()                 # after the update, so freed spots are used at once
            _update_rain(dt)
            if STATE["time_left"] <= 0.0:
                _end_game()

    if playing:
        _update_status(counts)
    _update_banner()


def _end_game():
    """Time is up: stop the rain and freeze the garden (tick() stops updating it)."""
    STATE["phase"] = "over"
    STATE["time_left"] = 0.0
    STATE["raining"] = False
    _tint_cloud()
    for drop in DROPS:
        if drop.alive:
            drop.alive = False
            _set_visible(drop.name, False)
    _refresh_rain_button()
    _refresh_start_button()


def _round_length():
    """Seconds per round: whatever the 'Game time' slider says (or the default before the window exists)."""
    if cmds.floatSliderGrp(GAME_SLIDER, exists=True):
        seconds = cmds.floatSliderGrp(GAME_SLIDER, query=True, value=True)
    else:
        seconds = GAME_SECONDS
    return max(seconds, 1.0)


def on_game_time_changed(*args):
    """The 'Game time' slider moved. It sets the length of the NEXT round.

    On the "Press Start Game" screen the banner shows the new length right away.
    A round that is already running keeps the time it started with, and the
    results screen is left alone.
    """
    if STATE["phase"] == "ready":
        STATE["game_seconds"] = _round_length()
        STATE["time_left"] = STATE["game_seconds"]
        _update_banner()


def _update_banner():
    """Show the countdown and score (or the final result) in the big banner."""
    phase = STATE["phase"]
    total = STATE["game_seconds"]

    if phase == "ready":
        text = "Press Start Game!     ({:g} seconds)".format(total)
        color, percent = BANNER_COLORS["ready"], 100
    elif phase == "playing":
        left = STATE["time_left"]
        text = "Time left: {}       Flowers collected: {}".format(
            _format_clock(left), STATE["score"]
        )
        # (short rounds get proportionally shorter warnings: a third and a ninth of the round)
        if left <= min(DANGER_SECONDS, total / 9.0):
            color = BANNER_COLORS["danger"]
        elif left <= min(WARN_SECONDS, total / 3.0):
            color = BANNER_COLORS["warn"]
        else:
            color = BANNER_COLORS["playing"]
        percent = int(round(100 * left / total))
    else:
        text = "TIME'S UP!       Flowers collected: {}".format(STATE["score"])
        color, percent = BANNER_COLORS["over"], 0

    shown = (text, color, percent)
    if shown != STATE["banner"]:          # only touch the window when something changed
        STATE["banner"] = shown
        cmds.text(BANNER_TEXT, edit=True, label=text, backgroundColor=color)
        cmds.progressBar(TIME_BAR, edit=True, progress=percent)


def _refresh_start_button():
    label = {"ready": "Start Game", "playing": "Restart", "over": "Play Again"}[STATE["phase"]]
    cmds.button(START_BUTTON, edit=True, label=label)


def _show_garden_status():
    """Fill in the status lines once, without moving time forward (dt = 0)."""
    _update_status(_update_flowers(0.0))


def _update_status(counts):
    """Show what's happening in the window (only redraw when something changed)."""
    total = len(FLOWERS)

    # "Health" of the garden: how much living, grown flower there is (0 to 100%).
    vitality = sum(f.growth * (1.0 - f.wither) for f in FLOWERS) / float(MAX_FLOWERS)
    percent = int(round(100 * vitality))

    line1 = "Flowers: {} of {}   (withered away so far: {})".format(
        total, MAX_FLOWERS, STATE["died"]
    )
    line2 = "Sun flowers: {} ({} waiting)     Rain flowers: {} ({} waiting)".format(
        counts["sun"], counts["sun_waiting"], counts["rain"], counts["rain_waiting"]
    )
    line3 = "Grown up: {}    Starving (withering fast): {}".format(
        counts["grown"], counts["starving"]
    )

    if (line1, line2, line3, percent) != STATE["ui"]:
        STATE["ui"] = (line1, line2, line3, percent)
        cmds.text(STATUS_TEXT, edit=True, label=line1)
        cmds.text(NEEDS_TEXT, edit=True, label=line2)
        cmds.text(LIFE_TEXT, edit=True, label=line3)
        cmds.progressBar(HEALTH_BAR, edit=True, progress=percent)


# --------------------------------------------------------------------------
# Step 8: button and slider callbacks
# --------------------------------------------------------------------------

def _cloud_exists():
    """True if the cloud is in the scene; otherwise warn the user."""
    if cmds.objExists(CLOUD_GROUP):
        return True
    cmds.warning("No cloud in the scene. Press 'Start Game' first.")
    return False


def on_slider_changed(*args):
    """Runs every time an X/Z slider moves. Moves the cloud (its height never changes)."""
    if not _cloud_exists():
        return
    x = cmds.floatSliderGrp(SLIDER_X, query=True, value=True)
    z = cmds.floatSliderGrp(SLIDER_Z, query=True, value=True)
    with _suspend_undo():            # playing the game is not an Undo step
        cmds.xform(CLOUD_GROUP, translation=(x, CLOUD_HEIGHT, z), worldSpace=True)


def on_nudge(dx, dz, *args):
    """Runs when a directional key is clicked (dx, dz are -1, 0 or 1)."""
    if not _cloud_exists():
        return
    step = cmds.floatSliderGrp(STEP_SLIDER, query=True, value=True)
    x, y, z = _cloud_position()
    with _suspend_undo():
        cmds.xform(
            CLOUD_GROUP,
            translation=(x + dx * step, CLOUD_HEIGHT, z + dz * step),
            worldSpace=True,
        )
    _sync_sliders_to_cloud()


def on_reset_clicked(*args):
    """'Reset' key in the middle of the keypad: cloud back to its start position."""
    if not _cloud_exists():
        return
    with _suspend_undo():
        cmds.xform(CLOUD_GROUP, translation=START_POSITION, worldSpace=True)
    _sync_sliders_to_cloud()


def on_rain_clicked(*args):
    """'Make it Rain' button: switch the rain on or off (only while playing)."""
    if not _cloud_exists():
        return
    if STATE["phase"] != "playing":
        cmds.warning("Press 'Start Game' first.")
        return
    STATE["raining"] = not STATE["raining"]
    with _suspend_undo():
        _tint_cloud()
    _refresh_rain_button()


def on_start_clicked(*args):
    """'Start Game' / 'Restart' / 'Play Again': build a fresh garden and start the clock."""
    _heal_undo()
    _flush_stale_undo()                  # a round that was played leaves stale Undo entries
    with _one_undo_step():               # one click in, one Ctrl+Z out
        create_scene()                   # a new, empty garden: group, ground, cloud, rain...

    # The flowers are the game's own business, so they are NOT part of the Undo step.
    with _suspend_undo():
        plant_first_flower()             # one seed; score 0, full time
        STATE["phase"] = "playing"
        _sync_sliders_to_cloud()
        _refresh_rain_button()
        _refresh_start_button()
        _show_garden_status()
        _update_banner()


def _delete_materials():
    """Delete the materials (and their shading groups) that the script made."""
    for name in MATERIALS:
        for node in (name + "_MAT", name + "_SG"):
            if cmds.objExists(node):
                cmds.delete(node)


def on_delete_clicked(*args):
    """'Delete' button: remove EVERYTHING the script made, in one Undo step."""
    if not cmds.objExists(ROOT_GROUP):
        cmds.warning("Nothing to delete. Press 'Start Game' to build the garden.")
        return

    _heal_undo()
    _flush_stale_undo()                   # a round that was played leaves stale Undo entries
    with _one_undo_step():                # one click in, one Ctrl+Z out
        cmds.delete(ROOT_GROUP)           # the group and everything inside it
        _delete_materials()               # materials live outside the group

    # Nothing to play with anymore: go back to the "ready" screen.
    STATE["phase"] = "ready"
    STATE["raining"] = False
    STATE["ui"] = None                    # so the next Start Game redraws the status lines
    _show_stopped_status("Garden deleted.", "Press 'Start Game' to plant a new one.")
    _refresh_rain_button()
    _refresh_start_button()
    _update_banner()


def _refresh_rain_button():
    label = "Stop Rain" if STATE["raining"] else "Make it Rain"
    cmds.button(RAIN_BUTTON, edit=True, label=label)


def _sync_sliders_to_cloud():
    """Set the slider values to match wherever the cloud currently is."""
    if not cmds.objExists(CLOUD_GROUP):
        return
    x, y, z = _cloud_position()
    cmds.floatSliderGrp(SLIDER_X, edit=True, value=x)
    cmds.floatSliderGrp(SLIDER_Z, edit=True, value=z)


# --------------------------------------------------------------------------
# Step 9: build the window
# --------------------------------------------------------------------------

def _make_position_slider(control_name, label, start_value):
    """Helper so we don't repeat the long slider settings twice."""
    half = GROUND_SIZE / 2.0
    return cmds.floatSliderGrp(
        control_name,
        label=label,
        field=True,
        minValue=-half,
        maxValue=half,
        fieldMinValue=-1000,
        fieldMaxValue=1000,
        value=start_value,
        step=0.1,
        precision=2,
        columnWidth3=(90, 70, 200),
        dragCommand=on_slider_changed,
        changeCommand=on_slider_changed,
    )


def _make_time_slider(control_name, label, start_value, min_value, max_value, command=None):
    """Helper for the 'how many seconds' sliders (command runs when the value changes)."""
    options = {}
    if command is not None:
        options["dragCommand"] = command
        options["changeCommand"] = command
    return cmds.floatSliderGrp(
        control_name,
        label=label,
        field=True,
        minValue=min_value,
        maxValue=max_value,
        fieldMinValue=0.5,
        fieldMaxValue=600.0,
        value=start_value,
        step=0.5,
        precision=1,
        columnWidth3=(90, 70, 200),
        **options
    )


def _make_key(label, command):
    """Helper: one big keypad button."""
    return cmds.button(label=label, height=38, command=command)


def _build_keypad():
    """Build the cross-shaped keypad (the cloud only moves along the ground).

        (empty)     [ Forward ]     (empty)
        [ Left ]    [  Reset  ]     [ Right ]
        (empty)     [  Back   ]     (empty)

    partial(on_nudge, 1, 0) means: "call on_nudge with dx=1, dz=0".
    """
    cmds.rowColumnLayout(
        numberOfColumns=3,
        columnWidth=[(1, 110), (2, 110), (3, 110)],
        columnSpacing=[(2, 6), (3, 6)],
        rowSpacing=[(2, 6), (3, 6)],
    )

    cmds.text(label="")
    _make_key("^  Forward", partial(on_nudge, 0, 1))
    cmds.text(label="")

    _make_key("<  Left", partial(on_nudge, -1, 0))
    _make_key("Reset", on_reset_clicked)
    _make_key("Right  >", partial(on_nudge, 1, 0))

    cmds.text(label="")
    _make_key("v  Back", partial(on_nudge, 0, -1))
    cmds.text(label="")

    cmds.setParent("..")


def show_cloud_gui():
    """Open the Cloud Controller window and start the live update."""
    # Deleting the old window also stops its old live update (see scriptJob below).
    if cmds.window(WINDOW_ID, exists=True):
        cmds.deleteUI(WINDOW_ID)

    cmds.window(
        WINDOW_ID,
        title="Cloud Controller",
        widthHeight=(430, 720),
        sizeable=False,
        resizeToFitChildren=True,
    )
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, columnOffset=("both", 10))

    # --- Scoreboard: countdown, score, and the final result ---
    cmds.separator(height=6, style="none")
    cmds.text(
        BANNER_TEXT, label="", align="center", height=44, font="boldLabelFont",
        enableBackground=True, backgroundColor=BANNER_COLORS["ready"],
    )
    cmds.progressBar(TIME_BAR, maxValue=100, width=410)

    # --- Garden status ---
    cmds.separator(height=6, style="in")
    cmds.text(label="Garden health", align="left", font="boldLabelFont")
    cmds.progressBar(HEALTH_BAR, maxValue=100, width=410)
    cmds.text(STATUS_TEXT, label="", align="left")
    cmds.text(NEEDS_TEXT, label="", align="left")
    cmds.text(LIFE_TEXT, label="", align="left")
    cmds.text(label="Yellow glow = wants sunlight     Blue bubbles = wants rain", align="left")

    # --- Move the cloud ---
    cmds.separator(height=6, style="in")
    cmds.text(label="Move the cloud", align="left", font="boldLabelFont")
    cmds.floatSliderGrp(
        STEP_SLIDER,
        label="Step size",
        field=True,
        minValue=0.1,
        maxValue=10.0,
        fieldMinValue=0.01,
        fieldMaxValue=100.0,
        value=DEFAULT_STEP,
        step=0.1,
        precision=2,
        columnWidth3=(90, 70, 200),
    )
    _build_keypad()
    sx, sy, sz = START_POSITION
    _make_position_slider(SLIDER_X, "Left / Right", sx)
    _make_position_slider(SLIDER_Z, "Forward / Back", sz)

    # --- Game ---
    cmds.separator(height=6, style="in")
    cmds.text(label="Game", align="left", font="boldLabelFont")
    _make_time_slider(
        GAME_SLIDER, "Game time (s)", GAME_SECONDS, MIN_GAME_SECONDS, MAX_GAME_SECONDS,
        command=on_game_time_changed,
    )
    cmds.text(label="The game time is used when you press Start Game.", align="left")

    # --- Weather and life cycle ---
    cmds.separator(height=6, style="in")
    cmds.text(label="Weather and life cycle", align="left", font="boldLabelFont")
    _make_time_slider(GROW_SLIDER, "Grow time (s)", DEFAULT_GROW_SECONDS, 2.0, 60.0)
    _make_time_slider(WITHER_SLIDER, "Wither time (s)", DEFAULT_WITHER_SECONDS, 5.0, 120.0)
    cmds.rowColumnLayout(
        numberOfColumns=3,
        columnWidth=[(1, 130), (2, 130), (3, 130)],
        columnSpacing=[(2, 10), (3, 10)],
    )
    cmds.button(RAIN_BUTTON, label="Make it Rain", height=32, command=on_rain_clicked)
    cmds.button(START_BUTTON, label="Start Game", height=32, command=on_start_clicked)
    cmds.button(DELETE_BUTTON, label="Delete", height=32, command=on_delete_clicked)
    cmds.setParent("..")
    cmds.text(label="Ctrl+Z = go back to the start of the round.", align="left")
    cmds.separator(height=6, style="none")

    cmds.showWindow(WINDOW_ID)
    _sync_sliders_to_cloud()
    _refresh_rain_button()
    _refresh_start_button()
    _show_garden_status()
    on_game_time_changed()               # make the banner match the new slider
    _update_banner()

    # Ask Maya to call tick() every time it is idle. "parent=WINDOW_ID" ties the
    # job to our window, so closing the window also stops the live update.
    cmds.scriptJob(event=["idle", tick], parent=WINDOW_ID)

    # Ctrl+Z: when the focus is in the viewport Maya does the Undo and tells us...
    cmds.scriptJob(event=["Undo", on_undo_event], parent=WINDOW_ID)
    # ...and when the focus is in this window, we catch the key ourselves.
    _install_undo_shortcut()


# --------------------------------------------------------------------------
# Run it
# --------------------------------------------------------------------------

def main():
    _heal_undo(blind=True)               # in case an earlier run left Undo stuck
    with _one_undo_step():               # running the script is ONE Undo step too
        create_scene()
    with _suspend_undo():                # (the flower and the window belong to the game, not to Undo)
        plant_first_flower()
        STATE["phase"] = "ready"         # the garden waits, frozen, until you press Start Game
        show_cloud_gui()


main()
