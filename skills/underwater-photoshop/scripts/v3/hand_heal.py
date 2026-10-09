# usage: hand_heal.py final.jpg patch_in.png patch_out.png review.jpg "x,y,r[,d];..."
# Adds hand-picked fixes to an existing RGBA patch (from subject_specks.py):
#   x,y,r    -> inpaint a small speck (circle radius r)
#   x,y,r,d  -> "disc": remove only the soft out-of-focus glow (low-frequency excess over the local level), keeps texture
import sys, cv2, numpy as np
inp, pin, pout, rev, spec = sys.argv[1:6]
img = cv2.imread(inp).astype(np.float32)
p = cv2.imread(pin, cv2.IMREAD_UNCHANGED).astype(np.float32); a = p[..., 3:4] / 255
cur = img * (1 - a) + p[..., :3] * a                      # image with the automatic patch applied
out = cur.copy(); H, W = cur.shape[:2]; touched = np.zeros((H, W), np.float32)
for item in [s for s in spec.split(";") if s.strip()]:
    v = item.split(","); x, y, r = int(v[0]), int(v[1]), int(v[2]); disc = len(v) > 3
    pad = r * 3; x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + pad), min(H, y + pad)
    roi = out[y0:y1, x0:x1]; m = np.zeros(roi.shape[:2], np.uint8); cv2.circle(m, (x - x0, y - y0), r, 255, -1)
    if disc:
        low = cv2.GaussianBlur(roi, (0, 0), max(3, r / 6))
        k = (2 * r + 1) | 1
        lvl = np.dstack([cv2.medianBlur(np.clip(roi[..., c], 0, 255).astype(np.uint8), min(k, 255) if min(k, 255) % 2 else min(k, 255) - 1) for c in range(3)]).astype(np.float32)
        excess = np.clip(low - lvl, 0, None)
        f = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), r / 4)[..., None]
        roi[:] = roi - excess * f
        touched[y0:y1, x0:x1] = np.maximum(touched[y0:y1, x0:x1], f[..., 0])
    else:
        m = cv2.dilate(m, np.ones((5, 5), np.uint8))
        h = cv2.inpaint(np.clip(roi, 0, 255).astype(np.uint8), m, 7, cv2.INPAINT_TELEA).astype(np.float32)
        f = cv2.GaussianBlur(m.astype(np.float32) / 255, (0, 0), 1.5)[..., None]
        roi[:] = roi * (1 - f) + h * f
        touched[y0:y1, x0:x1] = np.maximum(touched[y0:y1, x0:x1], f[..., 0])
alpha = np.maximum(a[..., 0], touched)
rgba = np.dstack([np.clip(out, 0, 255), alpha * 255]).astype(np.uint8); rgba[alpha == 0] = 0
cv2.imwrite(pout, rgba)
s = 0.3; cv2.imwrite(rev, cv2.resize(np.hstack([np.clip(cur * 2.2, 0, 255), np.clip(out * 2.2, 0, 255)]).astype(np.uint8), None, fx=s, fy=s, interpolation=cv2.INTER_AREA))
print("hand fixes:", len([s for s in spec.split(";") if s.strip()]))
