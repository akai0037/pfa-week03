# pfa-week03
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
