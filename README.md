# pfa-week03

## What this tool is

A small game that runs inside Maya. The script builds a garden with a cloud,
its shadow, and flowers, and opens a control window. You move the cloud and
turn rain on or off to grow as many flowers as you can before the time runs out.
Sun flowers only grow outside the cloud's shadow, and rain flowers only grow
while it is raining on them.

## How to run it

1. Open Maya and go to Windows > General Editors > Script Editor.
2. Make a Python tab, paste all of `code.py` into it, and press Ctrl+Enter.
3. The garden and the control window appear. Press "Start Game".

Controls: Left / Right / Forward / Back move the cloud, the rain button turns
rain on or off, and the "Game time" slider sets the round length (90 seconds by default).

## Ten lines explained

1. CLOUD_HEIGHT = 10.0
   
   START_POSITION = (-12.0, CLOUD_HEIGHT, 0.0)

   "CLOUD_HEIGHT" is equal to 10 and "START_POSITION" can read the number of "CLOUD_HEIGHT" even it changed the number. And with this, the cloud starts in the same place every time.

2. class Flower(object):

   Create an object named "Flower" so that I will not create the flowers and define the functions one by one.

3. def __init__(self, index, x, z, height, need):

   I know it create a function about creating the flowers. But I don't what can "_init_（）" do.

4. self.leaves = [prefix + "Leaf1_GRP", prefix + "Leaf2_GRP"]

   Create a list to put the name of leaves in it. Then I can control the leaves with "self.leaves".

5. def _stage_material(name, stage):

   return "{}_w{}".format(name, stage)

   Return a name using "name" and "stage" for the output.

6. for i, (x, y, z, radius) in enumerate(PUFFS):

   It's a loop, i is the index and (x, y, z, radius) are the values. But I don't know what can "enumerate" do.

7. for stage in range(WITHER_STAGES):

   It's a loop which go through based on "WITHER_STAGES" and the "stage" stores the current number.

8.  if need == "sun":

     else:

    If the flower needs sun. That means "need" is equal to "sun" and it will run the first part. Otherwise, it will run the "else" part.

9. del DROPS[:]

    Delete all items of the "DROPS" list. It's used to clear the raindrops.

10. if abs(x) > limit or abs(z) > limit:

    continue

    When it checks abs(x) or abs(z) is outside the limit, "continue" means skip and it will move to the next one.


# One loop paragraph
The paragraph starts at line 545. My tool uses a loop to create the flower petals. And it repeats the process of creating each petals. For each petal, it creates the model, finds it position and rotates it around the flower center until all the petals are done.


# The changed line
DEFAULT_STEP = CLOUD_HEIGHT / 5

I changed "DEFAULT_STEP = 2.0" so the movement of the cloud is based on its height. The higher the cloud is, the farther it moves.
