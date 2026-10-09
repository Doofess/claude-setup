# 100% crop (before | after) centred on the brightest clipped cluster inside the subject mask
import sys, os, cv2, numpy as np
import os
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.environ.get("UW_PROJECT") or os.getcwd()          # the photo folder (ARWs, lightroom, edited)
WORK = os.environ.get("UW_WORK") or os.path.join(PROJECT, ".claude-work")   # previews, masks, backups; safe to delete
stem, size = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 700
a = cv2.imread(os.path.join(WORK, "pop", stem + "_pop.jpg")); b = cv2.imread(os.path.join(WORK, "bak_prepop", stem + ".jpg"))
m = cv2.resize(cv2.imread(os.path.join(WORK, "pop", stem + "_mask.jpg"), 0), (a.shape[1], a.shape[0])) > 128
clip = ((a >= 254).any(2) & m).astype(np.float32)
d = cv2.boxFilter(clip, -1, (size // 2, size // 2))
y, x = np.unravel_index(d.argmax(), d.shape)
y0 = int(np.clip(y - size // 2, 0, a.shape[0] - size)); x0 = int(np.clip(x - size // 2, 0, a.shape[1] - size))
ca, cb = a[y0:y0+size, x0:x0+size].copy(), b[y0:y0+size, x0:x0+size]
ov = ca.copy(); ov[(ca >= 254).any(2)] = (255, 0, 255)   # magenta = clipped after
out = os.path.join(WORK, "pop", stem + "_100.jpg")
cv2.imwrite(out, np.hstack([cb, ca, ov]), [cv2.IMWRITE_JPEG_QUALITY, 92]); print(out, x0, y0)
