---
name: underwater-photoshop
description: Use when editing underwater or macro photos (Sony ARW or other RAW), applying Camera Raw settings, removing backscatter, making a subject "pop", building a dark-background look, or delivering JPEG + PSD edits through the local Photoshop install.
---

# Underwater edits in local Photoshop

The edit runs in the user's **local Photoshop 2026** through COM (`Photoshop.Application`), driven by JSX scripts. Camera Raw settings travel as an **XMP sidecar** next to the RAW, so the user can reopen any edit in Camera Raw or Lightroom and keep tweaking. The Adobe cloud connector (`mcp__claude_ai_Adobe__*`) cannot open ARW, works in 8-bit and its sliders are weak: use it only when the user asks for it by name. Nothing is uploaded to Adobe cloud.

Paid work for competitions. Judge every frame at 100% before calling it done.

## Setup per session

```powershell
$env:UW_PROJECT = "C:\path\to\photo folder"      # holds the ARWs (or a lightroom\ subfolder), edited\, and .claude-work\
$PY = "$HOME\.claude\skills\underwater-photoshop\.venv\Scripts\python.exe"
$S  = "$HOME\.claude\skills\underwater-photoshop\scripts"
```

Scripts take their folders from `UW_PROJECT`, `UW_RAW` (ARW folder, default `UW_PROJECT\lightroom` if it exists), `UW_DELIVER` (default `UW_PROJECT\edited`) and `UW_WORK` (default `UW_PROJECT\.claude-work`). Run Python with `-I`. A RAW the user drops in Downloads is copied into the project first so its sidecar sits beside it. A machine-wide mutex serialises Photoshop; one JSX runs at a time, and parallel subagents queue instead of colliding.

Missing venv: `python -m venv <skill>\.venv` then `pip install -r <skill>\requirements.txt`.

## Deliverables

`edited\<name>_edit.jpg` (full-res, q12, EXIF kept) + `edited\<name>_edit.psd` (16-bit, Camera Raw Smart Object base, every adjustment a named toggleable layer) + `<name>_before_after.jpg`. The user calls PSDs ".ps files".

## Workflow

1. **Read the frame.** EXIF (camera, lens, ISO, strobe or ambient), subject, background type: open water, dark background, sand or rubble. The background type picks the recipe below.
2. **Sidecar.** Write settings as a flat JSON of `crs:` keys, then `make_xmp.py settings.json <raw>.xmp` (`scripts/acr/`). Crop goes in as `HasCrop=True` plus normalized `CropTop/Left/Bottom/Right`.
3. **Preview loop.** Jobs file `src|out|maxEdge|quality`, one line per render, then `acr\run.ps1 -Jobs jobs.txt`. Iterate at ~1200 px until the look is right, then one full-size q12. `-Psd` renders the Smart Object PSD.
4. **Layer work** on the PSD when the frame needs it: `pop/` for subject pop, `v3/` for the dark-background stack, `edit/backscatter.py` and `edit/heal.py` for specks. Every Python re-save drops EXIF: finish with `edit/copy_exif.py <photoshop.jpg> <edited.jpg>`.
5. **QA at 100%.** `qa/qa.py outdir final.jpg` reports clipping, saturation, halo and noise and writes a `_100.jpg` strip of three crops. Read the strip. `pop/clipcheck.py` and `pop/crop100.py` do the same inside the subject mask. Fix what you see, then rerun.
6. Completion: every delivered frame has JPEG + PSD + before/after, QA strip read, no clipped subject pixels, EXIF present.

## Taste

Colours that pop a bit more, a bit sharper, subject centred, tight on macro, whole group kept on wide shots with room ahead of the subject. More saturation, contrast and sharpness than a judge-safe edit, but believable: get the pop on the **subject** through masked layers, not global sliders. Style hero: Tanner Mansell (@tannerunderwater): deep moody navy, top-bright bottom-dark falloff, near-zero haze, silver sharks with high contrast and texture, restrained cinematic saturation, sun rays.

Less zoom, more negative space: prefer the full frame and pad the canvas with black to centre a dark-background subject (`v3_run.py --pad t,b,l,r`) over a hard crop.

## Recipes

Starting points, each proven on a delivered frame. Auto WB runs yellow-green underwater; always set a custom temperature.

**Base (any frame).** Contrast +20..25, Highlights −30..−35, Blacks −15..−20, Texture +15..20, Clarity +10..15, Dehaze +15..25, Vibrance +15..20, lens profile on, post-crop vignette −10..−12. Sharpening 40..50 / radius 1.0 / masking 50..60. Luminance NR 35 at ISO 3200, 10 at ISO 500. ProcessVersion 15.4.

**Strobe macro, ISO 3200** (leaf sheep DSC05453): WB 3900K / Tint +38, Yellow hue −18, Green sat −15 lum −15, 4:5 crop.

**Ambient shark, blue water** (DSC05706): WB 7600K / Tint +48, Green hue +35, Aqua hue +15, Yellow sat −12, Dehaze +25.

**Tanner-style wide ambient** (hammerheads DSC05771, 24 mm, ISO 1000): As Shot WB, Exposure +0.20, Contrast +25, Highlights −60, Shadows +35, Whites −10, Blacks −25, Texture +15, Clarity +20, Dehaze +48, Aqua hue +20 sat −20 lum −10, Blue sat +5 lum −12, NR 20, vignette −12, 5:4 crop.

**v3 dark-background macro** (the user's favourite, from DSC02565_edit_v3.psd): `v3/v3_run.py <rawStem> <outStem> <cropT,L,B,R|none> [A|B|AB] [k=v overrides] [--pad] [--layers ds,levels,fill,hp] [--m thr=..,lev=bg]`. Recipe lives in `make_v3_xmp.py` (ProcessVersion 11.0, Exposure +1.75, Texture +45, Clarity +28, Orange sat +55, Blue sat −30...). Stack: Dust & Scratches on inverse subject, Levels black 50 on background, black fill outside the grown subject, High Pass r4 Soft Light 60% on the lit subject. Softened variant after "too much contrast": Contrast +8, Blacks −20, Shadows +25, Levels black 35 background only, High Pass 45%. Exposure rule: old master exposure + ~1.2 stops. Subjects on sand or rubble get `--layers levels,hp` (no fill) so they do not float on fake black; use `--m thr=300` on substrate or the bright-component union swallows the frame. Orange or red subjects (flatworm): keep their own colour settings instead of Orange +55, protect the rim with Highlights −85 / Whites −30, lift Shadows +55, limit Levels to `lev=bg`. Brightening a dark body exposes backscatter: heal it (`subject_specks.py`, `hand_heal.py`, `add_patch.jsx`).

**Subject pop** on a finished PSD: `pop/pop_run.py <prefix> lift contrast bgDarken subjSat gVib gSat gCon usmAmt usmRad featherPct`. Starts: lift 10, contrast 10, bgDarken 18..24 dark background or 8..12 blue water, subjSat 15 (8 grey sharks), gVib 15 / gSat 5, gCon 6, USM 60..65% r1.2. Idempotent on rerun. Clipping lessons: orange or golden subjects clip red fast, keep subjSat 2..6, lift 0..6, gSat 0. Grey sharks go cyan with positive subjSat: use −6..−8 and pop with lift and contrast. A subject filling the frame makes subjSat act global: keep it ~4. Bright white subjects: lift 0..4. Watch hot spots near eyes.

## Competition brief

`scripts/edit/MASTER_BRIEF.md` holds the judge rubric (UPY, Ocean Art consensus: less is more, clip nothing on the subject, minor crop and speck cleanup fine, EXIF kept) and the full master-pass procedure. Read it when the user says competition, judges, or "take this seriously".
