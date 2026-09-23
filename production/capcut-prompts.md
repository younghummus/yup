# CapCut (Seedance) prompts

Generate each shot in CapCut's AI video (Seedance). Compact versions of
`shots.yaml`, sized for in-app prompt limits.

**Images to attach**
- If CapCut offers *reference images*: add `reference/character/01-front-night-portal.jpg`
  and `reference/character/02-front-flying-sunset.png` to every shot.
- If it only offers a *start frame*: use `01-front-night-portal.jpg` for shot 1,
  and generate shots 2 and 3 as text-only (her description is in each prompt).

**Settings:** 16:9, highest quality, sound on. Pick 5s where 4s/6s aren't offered
and trim in the timeline (shot 1 → 4s, shot 3 → 6s; use 10s for shot 3 if 6s isn't available).

## Shot 1 — Portal burst (4s)

```
Static low-angle camera, no cuts, no zoom. Night over a dark ocean, full moon, Sydney Harbour skyline far on the horizon. The air above the water tears open into a blazing golden ring portal crackling with lightning. The same valkyrie from the reference — gold winged Spartan helmet, face hidden, long wavy strawberry-blonde hair, white breastplate with a crimson V, gold bracers and greaves, crimson pleated skirt — explodes out of the portal straight toward camera at extreme speed. Colossal white feathered wings fully spread, four times her height, wingtips breaking past the frame. A shockwave flattens the water below. Golden light pours from her body. Heavy motion blur, photorealistic, 35mm film grain. Sound: thunder-crack, crackling electricity, concussive boom, rushing wind.
```

## Shot 2 — Ocean fly-by (5s)

```
Camera locked just above the water surface, completely still, no cuts, no zoom. Night ocean, full moon. The same valkyrie — gold winged Spartan helmet, face hidden, long wavy strawberry-blonde hair, white breastplate with a crimson V, crimson pleated skirt, gold armour — rockets from the far background past the camera and out of frame in under two seconds, skimming a few metres above the sea. Colossal white wings four times her height cast a huge shadow on the water. Her speed rips the ocean into a sharp V-shaped wake, towering walls of spray peeling away on both sides. Golden light and lightning trail off her body. Whip-fast motion blur, camera shake as she passes, photorealistic, 35mm film grain. Sound: rising roar of wind, deafening whoosh, crashing spray.
```

## Shot 3 — Shoreline landing (6s)

```
Medium-wide shot, static camera, no cuts, no zoom. Rocky shoreline at night, ocean behind, full moon, Sydney Harbour skyline in the distance. The same valkyrie — gold winged Spartan helmet, face hidden, long wavy strawberry-blonde hair, white breastplate with a crimson V, crimson pleated skirt, gold armour — drops from the sky and slams down in a crouch, cracking the rock; a ring of dust and sea spray blasts outward. She rises into a battle stance, weight low, fists raised. Her colossal white feathered wings sweep fully open behind her, filling the frame edge to edge. Golden light pulses across her armour with small arcs of lightning, dramatic rim lighting, photorealistic, 35mm film grain. Sound: heavy impact, cracking stone, rushing feathers, electric hum.
```

## Tips
- Generate 2–3 variations per shot and keep the best.
- If her armour or helmet drifts, regenerate with the reference images attached.
- Put the three clips in order on the CapCut timeline; add a quick flash or whip
  transition between shot 1 → 2 and a hard cut into shot 3's impact.

## v2 — single 15s generation (Seedance 2.5, 16:9, 15s)

Fixes from take 1 (too slow; upright hovering pose with dangling legs and arms at
her sides; head-on approach that never passes camera; walks in instead of landing):
explicit real-time speed, locked superhero flight pose with both fists forward,
side-angle pass, vertical drop for the landing.

```
Fast-paced action sequence, 15 seconds, three shots with hard cuts, real-time speed, NOT slow motion, photorealistic, 35mm film grain, night, full moon, Sydney Harbour skyline in the distance. The same valkyrie from the reference images in every shot: gold winged Spartan helmet with face hidden, long wavy strawberry-blonde hair, white breastplate with a crimson V, gold bracers and greaves, crimson pleated skirt, colossal white feathered wings four times her height.

FLIGHT POSE whenever she flies: body horizontal and rigid like a missile, both arms locked straight out in front of her with both fists clenched and leading, head tucked between her arms, legs straight and together behind her, wings fully spread and held rigid, not flapping. Never upright, never hovering, legs never dangling.

Shot 1 (0-3s), static low-angle camera over a dark ocean: a blazing golden ring portal tears open above the water with crackling lightning. In under one second she blasts out of the portal fists-first in the flight pose, straight at the camera, filling the frame. A shockwave slams the water flat. Extreme motion blur.

Shot 2 (3-8s), camera locked low beside the water surface, static, side angle: she streaks across the frame from far left to right in the flight pose in about one second, fists leading, a few metres above the sea, and is gone. Her speed tears the ocean into a sharp V-shaped wake, walls of spray exploding up on both sides and hanging in the air after she passes. Golden light and lightning trail behind her. Violent camera shake as she passes.

Shot 3 (8-15s), medium-wide static shot on a rocky shoreline: she plummets vertically from the top of the frame at full speed and slams down in a three-point crouch, fist to the ground, shattering the rock, a ring of dust and spray blasting outward. She rises into a battle stance, weight low, both fists raised, and her wings snap fully open, filling the frame edge to edge. Golden light pulses across her armour with small arcs of lightning.

Sound: no music. Thunder-crack, concussive boom, sonic whoosh as she passes, crashing spray, heavy impact, cracking stone.

## v3 — colossal wings (Seedance 2.5, 16:9, 10s, then speed-ramp)

Take 2 was still slow and the wings came out ~her height. Generate at 10s and run
`production/speedramp.sh` on the result. Wing size is described against real-world
scale because the reference photos pull the model toward normal-sized wings.

```
Fast-paced action sequence, three shots with hard cuts, real-time speed, NOT slow motion, photorealistic, 35mm film grain, night, full moon, Sydney Harbour skyline in the distance. The same valkyrie from the reference images: gold winged Spartan helmet with face hidden, long wavy strawberry-blonde hair, white breastplate with a crimson V, gold bracers and greaves, crimson pleated skirt.

COLOSSAL WINGS, much larger than in the reference images: each wing is longer than a bus, total wingspan eight times her body height, like a giant eagle's wings on a human. She looks small between her own wings. The wings always extend far beyond both edges of the frame.

FLIGHT POSE whenever she flies: body horizontal and rigid like a missile, both arms locked straight out in front of her with both fists clenched and leading, legs straight together behind her, giant wings held rigid, not flapping. Never upright, never hovering.

Shot 1: a blazing golden ring portal tears open above a dark ocean with crackling lightning; she blasts out of it fists-first in the flight pose, straight at the camera, in under one second. A shockwave slams the water flat.

Shot 2: camera low beside the water, side angle: she streaks across the whole frame left to right in the flight pose in under one second and is gone, her giant wings spanning the full width of the ocean. The sea tears open into a V-shaped wake with walls of spray exploding up on both sides.

Shot 3: rocky shoreline: she plummets vertically from the sky and slams into a three-point landing, shattering the rock, dust and spray blasting outward. She rises into a battle stance with both fists raised, and her colossal wings snap open, far wider than the frame.

Sound: no music. Thunder-crack, concussive boom, sonic whoosh, crashing spray, heavy impact.
```

## Take 3 review
- Shot 1 (portal burst) and shot 3 (landing) are keepers; wings are much bigger.
- Shot 2 failed: she is only a gold streak for ~0.5s, then 4s of an empty wave.
  Pose still upright with bent arms, not fists forward.
- Plan: regenerate shot 2 alone (5s) with the prompt below, splice it into take 3.

### Shot 2 only (Seedance 2.5, 5s, 16:9, 3 photos attached)

```
One continuous shot, real-time speed, NOT slow motion, photorealistic, 35mm film grain. Night, dark ocean, full moon. Camera low just above the water, side angle, static. The valkyrie from the reference images — gold winged Spartan helmet, long wavy strawberry-blonde hair, white breastplate with a crimson V, crimson pleated skirt, gold armour — flies across the frame from left to right, clearly visible the whole time, skimming a few metres above the sea. Superman flight pose: body horizontal, both arms locked straight out in front with both fists clenched and leading, legs straight together behind her. Colossal white wings, each longer than a bus, spread wide and rigid, not flapping. Her speed rips the ocean into a V-shaped wake with walls of spray exploding up behind her. Golden light and lightning trail off her body. Motion blur on the water, she stays sharp. Sound: roaring wind, sonic whoosh, crashing spray.
```

## v4 — previz-driven (the reliable method)

Text alone keeps producing slow motion, an upright pose and small wings. Instead,
`production/previz.py` renders a 15s animatic (`renders/valkyrie-previz.mp4`) that
locks timing, camera, fists-first pose and wing scale. Seedance follows a reference
video's motion far more strictly than words, so it only has to make it photoreal.

**CapCut:** Seedance 2.5 · 15s · 16:9. Attach, in this order:
1. `renders/valkyrie-previz.mp4` (motion)
2. `reference/stills/huge-wings-flying.jpg` (her + wing size)
3. `reference/stills/huge-wings-stance.jpg` (her + wing size)
4. `reference/character/01-front-night-portal.jpg` (costume detail)

```
Remake @Video1 as photorealistic live-action cinema. Copy @Video1 exactly: the same three shots, the same cuts, the same timing, the same camera positions, the same speed of every movement, the same poses and the same wing size. Do not slow anything down. The flat cartoon figure in @Video1 is the valkyrie from @Image1, @Image2 and @Image3: gold winged Spartan helmet, face hidden, long wavy strawberry-blonde hair, white breastplate with a crimson V, crimson pleated skirt, gold bracers and greaves, colossal white feathered wings as huge as in @Image1 and @Image2. When flying she leads with both fists straight out in front of her. Night, full moon, Sydney Harbour skyline, real ocean water, real spray, real rock, golden light and lightning. 35mm film grain. Sound: no music, thunder-crack, concussive boom, sonic whoosh, crashing spray, heavy impact, cracking stone.
```
