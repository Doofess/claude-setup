# usage: backscatter.py in.jpg out.png [--dark 60] [--maxsize 41] [--thresh 18] [--mask maskout.png]
# Removes small bright specks (backscatter) that sit on DARK background only, via inpainting.
# Subject protection: only pixels whose surroundings (heavy blur) are darker than --dark are eligible,
# and only blobs smaller than --maxsize px across are touched. Writes the mask for review.
import sys, argparse, cv2, numpy as np
ap = argparse.ArgumentParser(); ap.add_argument("inp"); ap.add_argument("out")
ap.add_argument("--dark", type=int, default=60); ap.add_argument("--maxsize", type=int, default=41)
ap.add_argument("--thresh", type=int, default=18); ap.add_argument("--mask", default=None)
a = ap.parse_args()
img = cv2.imread(a.inp, cv2.IMREAD_COLOR); L = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
k = a.maxsize | 1
tophat = cv2.morphologyEx(L, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
spots = (tophat > a.thresh).astype(np.uint8)
bg = cv2.GaussianBlur(L, (0, 0), sigmaX=k * 2)
darkbg = (bg < a.dark).astype(np.uint8)
# keep only small components fully inside dark background
n, lab, stats, _ = cv2.connectedComponentsWithStats(spots, 8)
mask = np.zeros_like(spots)
for i in range(1, n):
    x, y, w, h, area = stats[i]
    if max(w, h) <= a.maxsize and darkbg[y:y+h, x:x+w].mean() > 0.95:
        mask[lab == i] = 255
mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
out = cv2.inpaint(img, mask, 5, cv2.INPAINT_TELEA)
cv2.imwrite(a.out, out)
if a.mask: cv2.imwrite(a.mask, mask)
print("specks removed:", int((mask > 0).sum() > 0) and n - 1, "masked px:", int((mask > 0).sum()))
