> Paths in this brief: `$SP` = this skill's `scripts/` folder, `$SP/venv/Scripts/python` = the skill venv `~/.claude/skills/underwater-photoshop/.venv/Scripts/python.exe`. Work files go to `%UW_WORK%` (default `<photo folder>\.claude-work`), not a scratchpad.

# MASTER PASS: competition grade

Read this AFTER BRIEF.md. The same rules apply: local Photoshop only, no Adobe/cloud/MCP/web tools, never touch the RAWs, render only via render_locked.ps1, small job files.

The friend is entering these in an underwater photo competition. The first pass was reviewed at 100% and most frames would NOT survive a judge's full-size inspection. You are the final editor. Standard: Underwater Photographer of the Year / Ocean Art winners.

## What judges actually do (from published judges' comments and rules)
- They view at FULL SIZE. "Overcooked images look fine as thumbnails; at full size the excessive processing becomes glaringly obvious."
- The flaw they name most: heavy-handed saturation/vibrance, over-sharpening, heavy clarity/texture/dehaze/contrast ("wrecks file integrity").
- "Soft focus and/or missing the exposure will weigh against an image." Rarity never rescues a soft frame. Important areas clipped to 0 or 255 are "unlikely to be selected".
- Blues are "tricky to get right": water must look like real water, natural and believable, not neon teal or electric navy.
- Minor cropping and tonal adjustment are expected; significant cropping is "looked down on", and entries need real resolution for exhibition prints.
- Cleaning backscatter and removing unwanted floating objects is allowed (UPY explicitly; Ocean Art "limited"). Do NOT remove or add animals, paint backgrounds black, or replace anything. The frame must stay honest: winners are checked against the RAW.
- Technical polish counts: no chromatic aberration / purple-blue fringing, no halos, no banding in water, clean blacks that still hold subject shadow detail, no dust or specks.

## Non-negotiable checks before you call an image done
1. **Eye/subject focus at 100%**: crop 600x600 around the eye (python/cv2) and Read it. If the eye is not sharp, the frame is rejected: pick another frame (scout_all.tsv plus neighbouring stems in thumbs/) or report "no competition-grade frame".
2. **Fringing**: enable Camera Raw CA removal and defringe in the sidecar: `"AutoLateralCA": "1", "DefringePurpleAmount": "8", "DefringePurpleHueLo": "30", "DefringePurpleHueHi": "70", "DefringeGreenAmount": "6", "DefringeGreenHueLo": "40", "DefringeGreenHueHi": "60"`. Raise the amounts to 12-20 only if fringing remains, and check it doesn't eat real blue/green subject colour (blue rings: use purple defringe only, and verify).
3. **Backscatter/specks**: on dark backgrounds run `backscatter.py` on the full-size render, inspect the mask, then remove remaining specks near the subject by hand with `spots.py` (x,y,r in full-res pixels, found by cropping and Reading). Never inpaint over the animal. Re-check at 100%.
4. **Restraint**: Saturation 0 (use small per-colour HSL moves instead), Vibrance <= +15, Texture <= +15, Clarity <= +12, Dehaze <= +20 on macro and <= +35 on blue water, Sharpening 30-45 / radius 0.8-1.0 / detail 20-25 / masking 60-80, no halos at 100%. Vignette <= -10 or none. Build contrast with Highlights/Shadows/Whites/Blacks rather than big Contrast values.
5. **Histogram**: no clipped highlights on the subject (Highlights/Whites down). Blacks may be true black only in the background. Check the qa.py numbers.
6. **Noise**: LuminanceSmoothing 15-35 by ISO. Over-smoothing (plastic skin) is a fault too. Grain in water: slightly more NR and less sharpening in flat areas (use masking).
7. **Colour truth**: whites neutral (sample sand or white tips: R, G, B within about 8 of each other), body colours believable, water natural. Compare with the camera JPEG thumb to make sure you have not drifted into a fantasy palette.
8. **Crop**: keep as much of the frame as possible; aim for >= 12 MP after the crop (>= 4000 px long edge) unless the subject is tiny. Place the subject with intent (eye on a third, or centred and symmetric). No cut body parts unless the original already cuts them.
9. **Final QA**: run `"$SP/venv/Scripts/python" -I "$SP/qa/qa.py" "$SP/qa/<yourkey>" <final.jpg>` and Read the `_100.jpg` strip; fix anything you see.

## Audit of the first pass (what is wrong now; fix or replace)
- 01 Nautilus-Reflection DSC02568: eye sharp (good). Blue CA fringing on edges; small specks in the black; mild over-sharpening (halo 17). Fix CA, clean specks, soften sharpening.
- 02 Nautilus-Eating DSC02548: soft at 100% (shell texture mushy). DSC02549: very soft. Re-examine every argonaut frame (DSC02538 to DSC02568 and the *_id copies) for the sharpest EATING frame(s). If none is sharp, deliver the best one and flag it "not competition-sharp".
- 03a Leaf-Sheep-Wide DSC03247: good; small CA; keep and polish.
- 03b Mom-Baby DSC05532: REJECT. Oversaturated (mean sat 240), clipped, noisy and soft (ISO 6400). Find a sharper pair frame (check the DSC0553x neighbours, DSC04764, DSC0475x, DSC05453) or deliver with an honest flag.
- 03c Mom-Eggs DSC04905: acceptable; rhinophores sharp; eggs out of focus by design. Polish only.
- 04 Palau-Shark DSC05706: REJECT as-is. Over-saturated teal water (sat 236), soft and banded water at 100%, flat shark. Redo from the RAW with natural blue, no neon, less dehaze. Check DSC04968 and DSC05061 as alternatives. If the shark is simply soft, say so.
- 05 Jellyfish DSC05592: strong; 5% highlight clipping is acceptable only if it is the sun disc itself; reduce halo. DSC05614: top half soft (water on the dome); OK for an over/under but flag it. DSC05301: water over-saturated (209) and banded, subject slightly soft; tone it down and check DSC05271 as the "no people" alternative.
- 06 Eels DSC02444: eye tack sharp. Rainbow CA specks in the blacks: fix CA and clean specks. Good candidate.
- 08 Frogfish-Eye DSC02306: eye good, purple fringe on the eye rim; fix CA. Good candidate.
- 09 Flatworm DSC01963: edge slightly soft, blue/purple fringe along the edge, backscatter still present NEXT to the subject (the auto tool protects that zone). Fix CA; hand-remove the remaining specks with spots.py; compare DSC01961/01967 for sharpness.
- 10 Mototi DSC01604: eye sharp, good. Remove the thin strand in front of the eye only if it is a floating object (allowed); polish.
- 11 Cuttlefish DSC01391: tack sharp but over-sharpened (halo 24): re-render with gentler sharpening. DSC02397 (flamboyant): soft at 100%, CA: replace with a sharper flamboyant frame (DSC02401 etc.) or DSC02238 / DSC03165.
- 12 Juvenile-Scorpionfish DSC02701: REJECT. 2661x1774 px crop, soft. Pick a frame that is sharp at full size: check DSC01423/DSC01424 (manual), DSC02947/DSC02948, DSC00756/DSC00757; keep the crop modest.
- 13 Mating-Blue-Rings DSC02625: rings sharp; purple fringing on the rings; specks in the dark; the busy background cannot be fixed. Fix CA (purple only; verify the rings keep their blue), clean specks.
- 14 Bamboo DSC02662: grainy blacks, rainbow CA specks; verify the shark's eye is sharp (the sand looks sharper than the shark). DSC02669: verify eye focus. Fix CA, NR, clean specks.

## Deliverables (overwrite the first-pass files; same naming)
- `edited\friend-list\<NN>-<Subject>_<stem>.jpg` full-res quality 12, and `.psd` (RAW smart object plus any "Backscatter removed" pixel layer via add_layer_locked.ps1).
- If you replace a frame, delete the old pair you are replacing (only files with YOUR list number) so each item has only the chosen frame(s).
- EXIF must survive: Photoshop keeps it in the JPEG it writes, but python/cv2 re-saves DROP it. After any python edit, restore it with `"$SP/venv/Scripts/python" -I "$SP/edit/copy_exif.py" <photoshop.jpg> <cleaned.jpg>` (this re-saves at q97).

## Report (short)
Per item: final stem, verdict (competition-ready / usable with caveat / no good frame), the one-line reason, key settings, what you fixed from the audit, remaining weakness.

## Extra tool
`SP\edit\E\bs_protect.py` is a subject-protecting variant of backscatter.py written by editor E (it masks the subject so specks on skin/edges are never touched). Read its header for usage; prefer it on black-background shots, then finish with spots.py by hand.

## Note for the relaunched master pass
A previous master attempt was interrupted mid-work. Sidecars next to the RAWs (and 03a/03c JPEGs) may hold partially applied master settings. Trust nothing: re-read the current sidecar and the first-pass JSON, render a fresh preview, and verify before building on it. First-pass final JPEGs are backed up in SPditak\ for comparison.
