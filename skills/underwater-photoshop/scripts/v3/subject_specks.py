# usage: subject_specks.py final.jpg subjmask.tif out_patch.png out_review.jpg [thr=14] [maxsize=31] [dark=95] [discs=1]
# Finds backscatter left INSIDE the subject area after the v3 stack (the black fill already hides the open background):
#   specks = small bright points (white top-hat) whose surroundings are dark (body, not the bright rim)
#   discs  = soft out-of-focus backscatter discs (larger, low-contrast, round) on dark surroundings
# Inpaints them and writes ONLY the healed pixels (RGBA, transparent elsewhere) for a toggleable top layer.
import sys, cv2, numpy as np
inp, maskp, outp, revp = sys.argv[1:5]
opt = dict(thr="14", maxsize="31", dark="95", discs="1"); opt.update(a.split("=", 1) for a in sys.argv[5:])
thr, maxs, dark, discs = int(opt["thr"]), int(opt["maxsize"]), int(opt["dark"]), opt["discs"] == "1"
img = cv2.imread(inp); L = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
H, W = L.shape
zone = cv2.resize(cv2.imread(maskp, 0), (W, H)) < 128        # ds mask is 255 on background, 0 on subject
zone = cv2.dilate(zone.astype(np.uint8), np.ones((81, 81), np.uint8)) > 0   # subject + 40 px fringe
surround = cv2.medianBlur(L, 61)                                           # local level without the speck
mask = np.zeros((H, W), np.uint8)
k = maxs | 1
th = cv2.morphologyEx(L, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
n, lab, st, _ = cv2.connectedComponentsWithStats((th > thr).astype(np.uint8), 8)
cnt = 0
for i in range(1, n):
    x, y, w, h, a = st[i]
    if max(w, h) > maxs or a < 3: continue
    cy, cx = y + h // 2, x + w // 2
    if not zone[cy, cx] or surround[cy, cx] > dark: continue
    mask[lab == i] = 255; cnt += 1
dcnt = 0
if discs:
    th2 = cv2.morphologyEx(cv2.GaussianBlur(L, (0, 0), 3), cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(opt.get("dk", "151")),) * 2))
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats((th2 > float(opt.get("dthr", "9"))).astype(np.uint8), 8)
    for i in range(1, n2):
        x, y, w, h, a = st2[i]
        if not (30 <= max(w, h) <= int(opt.get("dmax", "130"))) or min(w, h) < 0.7 * max(w, h) or a < 0.6 * w * h: continue  # round blobs only
        cy, cx = y + h // 2, x + w // 2
        if not zone[cy, cx] or surround[cy, cx] > dark * 0.8: continue
        mask[lab2 == i] = 255; dcnt += 1
mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
healed = cv2.inpaint(img, mask, 9, cv2.INPAINT_TELEA)
alpha = cv2.GaussianBlur(mask, (0, 0), 1.5)
rgba = np.dstack([healed, alpha]); rgba[alpha == 0] = 0
cv2.imwrite(outp, rgba)
ov = img.copy(); cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
cv2.drawContours(ov, cs, -1, (0, 255, 0), 3)
s = 1800 / W; cv2.imwrite(revp, np.hstack([cv2.resize(ov, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), cv2.resize(healed, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)]))
print(f"specks {cnt}  discs {dcnt}  healed px {int((mask > 0).sum())}")
