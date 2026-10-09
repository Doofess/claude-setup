# usage (--m thr=..,lo=..,hi=..,lev=bg passes mask options): v3_run.py <rawStem> <outStem> <cropT,L,B,R | none> [stage A|B|AB] [k=v sidecar overrides ...] [--b dsR,dsT,levBlack,hpR,hpOp]
# Applies the DSC02565_edit_v3 recipe to lightroom\<rawStem>.ARW: sidecar -> stage A (render + Select Subject) -> masks.py -> stage B (layered PSD + JPEG).
# Outputs land in %UW_WORK%\v3\out\<outStem>.psd/.jpg for review; nothing in edited is touched.
# Env: UW_PROJECT (photo folder, default cwd) / UW_RAW (ARW folder, default UW_PROJECT\lightroom or UW_PROJECT) / UW_WORK (default UW_PROJECT\.claude-work)
import sys, os, subprocess, ctypes
def longpath(p):
    b = ctypes.create_unicode_buffer(1024); ctypes.windll.kernel32.GetLongPathNameW(p, b, 1024); return b.value or p
import os
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.environ.get("UW_PROJECT") or os.getcwd()          # the photo folder (ARWs, lightroom, edited)
WORK = os.environ.get("UW_WORK") or os.path.join(PROJECT, ".claude-work")   # previews, masks, backups; safe to delete
LR = os.environ.get("UW_RAW") or (os.path.join(PROJECT, "lightroom") if os.path.isdir(os.path.join(PROJECT, "lightroom")) else PROJECT)  # folder holding <rawStem>.ARW
PY = sys.executable
args = sys.argv[1:]
bparams = "8,20,50,4,60"; mopts = []; pad = ""; layers = ""
if "--layers" in args:                   # subset of ds,levels,fill,hp (default all)
    i = args.index("--layers"); layers = args[i + 1]; del args[i:i + 2]
if "--pad" in args:                      # black canvas top,bottom,left,right (px) for centring the subject
    i = args.index("--pad"); pad = args[i + 1]; del args[i:i + 2]; mopts.append("pad=" + pad)
if "--m" in args:
    i = args.index("--m"); mopts += args[i + 1].split(","); del args[i:i + 2]
if "--b" in args:
    i = args.index("--b"); bparams = args[i + 1]; del args[i:i + 2]
raw, out, crop = args[0], args[1], args[2]
stage = args[3] if len(args) > 3 and args[3] in ("A", "B", "AB") else "AB"
over = [a for a in args[3:] if "=" in a]
V = HERE; W = os.path.join(WORK, "v3", "work", out); O = os.path.join(WORK, "v3", "out"); os.makedirs(W, exist_ok=True); os.makedirs(O, exist_ok=True)
fw = lambda p: p.replace("\\", "/")
def ps(jsx, params, line):
    open(params, "w", encoding="utf-8").write(line + "\n")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(V, "run_jsx.ps1"), "-Jsx", os.path.join(V, jsx), "-Params", params], capture_output=True, text=True)
    print(jsx, r.stdout.strip(), r.stderr.strip()[:300])
    return "OK" in r.stdout
rawp = os.path.join(LR, raw + ".ARW")
if "A" in stage:
    ov = list(over)
    if crop != "none":
        t, l, b, rr = crop.split(",")
        ov += ["HasCrop=True", "CropAngle=0", "CropConstrainToWarp=0", f"CropTop={t}", f"CropLeft={l}", f"CropBottom={b}", f"CropRight={rr}"]
    subprocess.run([PY, "-I", os.path.join(V, "make_v3_xmp.py"), os.path.join(LR, raw + ".xmp")] + ov, check=True)
    for f in ("base.tif", "subj.tif"):
        if os.path.exists(os.path.join(W, f)): os.remove(os.path.join(W, f))
    if not ps("stageA.jsx", os.path.join(W, "a.txt"), "|".join([fw(rawp), fw(os.path.join(W, "base.tif")), fw(os.path.join(W, "subj.tif"))])): sys.exit(1)
    r = subprocess.run([PY, "-I", os.path.join(V, "masks.py"), os.path.join(W, "base.tif"), os.path.join(W, "subj.tif"), W] + mopts, capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip()[-500:])
if "B" in stage:
    psd, jpg = os.path.join(O, out + ".psd"), os.path.join(O, out + ".jpg")
    for f in (psd, jpg):
        if os.path.exists(f): os.remove(f)
    ps("stageB.jsx", os.path.join(W, "b.txt"), "|".join([fw(rawp), fw(W), fw(psd), fw(jpg)] + bparams.split(",") + [pad, layers]))
