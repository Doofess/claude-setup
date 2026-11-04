# usage: pop_run.py <name-prefix> subjLift subjContrast bgDarken subjSat gVib gSat gContrast usmAmt usmRad featherPct
# Finds %UW_DELIVER%\<prefix>*.psd (default %UW_PROJECT%\edited), backs up its JPEG once, runs pop.jsx via the locked runner,
# writes the new JPEG over the deliverable and a mask preview + before/after strip into %UW_WORK%\pop.
import sys, os, glob, shutil, subprocess, cv2, numpy as np
import os
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.environ.get("UW_PROJECT") or os.getcwd()          # the photo folder (ARWs, lightroom, edited)
WORK = os.environ.get("UW_WORK") or os.path.join(PROJECT, ".claude-work")   # previews, masks, backups; safe to delete
D = os.environ.get("UW_DELIVER") or os.path.join(PROJECT, "edited")   # folder holding the <prefix>*.psd deliverables
prefix, vals = sys.argv[1], sys.argv[2:]
psds = glob.glob(os.path.join(D, prefix + "*.psd"))
assert len(psds) == 1, psds
psd = psds[0]; stem = os.path.splitext(os.path.basename(psd))[0]; jpg = os.path.join(D, stem + ".jpg")
out = os.path.join(WORK, "pop"); os.makedirs(out, exist_ok=True)
bak = os.path.join(WORK, "bak_prepop"); os.makedirs(bak, exist_ok=True)
if not os.path.exists(os.path.join(bak, stem + ".jpg")): shutil.copy2(jpg, bak)
newjpg = os.path.join(out, stem + "_pop.jpg"); mask = os.path.join(out, stem + "_mask.jpg")
for f in (newjpg, mask):
    if os.path.exists(f): os.remove(f)
params = os.path.join(out, stem + ".params.txt")
open(params, "w", encoding="utf-8").write("|".join([psd, newjpg, mask] + vals) + "\n")
r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(HERE, "pop_locked.ps1"), "-Params", params], capture_output=True, text=True)
print(r.stdout.strip(), r.stderr.strip()[:300])
if os.path.exists(newjpg):
    shutil.copy2(newjpg, jpg)
    a = cv2.imread(os.path.join(bak, stem + ".jpg")); b = cv2.imread(newjpg); m = cv2.imread(mask)
    h = 560; rs = lambda x: cv2.resize(x, (int(x.shape[1] * h / x.shape[0]), h), interpolation=cv2.INTER_AREA)
    cv2.imwrite(os.path.join(out, stem + "_cmp.jpg"), np.hstack([rs(a), rs(b), rs(m)]), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print("cmp:", os.path.join(out, stem + "_cmp.jpg"))
