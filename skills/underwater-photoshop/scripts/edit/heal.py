# heal.py in out "x,y,r;..." [sigma=35] : smooth-background heal for larger specks on dark/gradient areas.
# Fills each circle with a normalized-convolution estimate of the surrounding background (circle excluded),
# feathers the edge, and adds low-amplitude noise matched to the surrounding ring so the patch is not plastic.
import sys, cv2, numpy as np
inp, out, spec = sys.argv[1], sys.argv[2], sys.argv[3]; sigma = float(sys.argv[4]) if len(sys.argv) > 4 else 35
img = cv2.imread(inp).astype(np.float32); H, W = img.shape[:2]; rng = np.random.RandomState(1)
for s in [q for q in spec.split(";") if q.strip()]:
    x, y, r = [int(float(v)) for v in s.split(",")]; sg = max(sigma, r); R = int(r * 3 + 3 * sg)
    x0, y0, x1, y1 = max(0, x - R), max(0, y - R), min(W, x + R), min(H, y + R)
    sub = img[y0:y1, x0:x1]; m = np.zeros(sub.shape[:2], np.float32); cv2.circle(m, (x - x0, y - y0), r, 1, -1)
    ex = np.zeros_like(m); cv2.circle(ex, (x - x0, y - y0), int(r * 1.6) + 4, 1, -1); valid = 1 - ex
    num = cv2.GaussianBlur(sub * valid[..., None], (0, 0), sg); den = cv2.GaussianBlur(valid, (0, 0), sg)[..., None]
    bg = num / np.maximum(den, 1e-3)
    ring = np.zeros_like(m); cv2.circle(ring, (x - x0, y - y0), int(r * 1.6) + 30, 1, -1); ring *= valid
    hf = sub - cv2.GaussianBlur(sub, (0, 0), 3)                           # local fine noise
    sd = np.sqrt((hf[ring > 0] ** 2).mean(axis=0)) if ring.any() else np.zeros(3)
    noise = cv2.GaussianBlur(rng.normal(0, 1, sub.shape).astype(np.float32), (0, 0), 1.2); noise *= sd / max(noise.std(), 1e-6)
    feather = cv2.GaussianBlur(m, (0, 0), max(2.0, r * 0.15))[..., None]
    img[y0:y1, x0:x1] = sub * (1 - feather) + (bg + noise) * feather
cv2.imwrite(out, np.clip(img, 0, 255).astype(np.uint8)); print("healed", spec)
