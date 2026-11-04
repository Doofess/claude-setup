# v3 recipe, mask builder. usage: masks.py base.tif subj.tif outdir [thr=38] [lo=45] [hi=135] [lev=full|bg]
# Rebuilds the four masks of DSC02565_edit_v3.psd (measured from that file):
#   subject  = Photoshop Select Subject, plus any large bright connected object it missed (faint arms, prey, blade tips)
#   ds       = inverse hard subject                       -> Dust & Scratches only on the background
#   levels   = 1 - subject * lumRamp                      -> black point 50 on background + dark parts of the subject
#   fill     = inverse(subject grown 20 px, Gaussian 20)  -> pure black background, soft edge
#   hp       = subject * lumRamp                          -> High Pass detail only on lit subject areas
#   lumRamp  = clip((L - 45) / 90, 0, 1)  (L = base luminance; ramp matched to the reference masks)
import sys, os, cv2, numpy as np
base, subjp, out = sys.argv[1], sys.argv[2], sys.argv[3]
opt = dict(thr='38', lo='45', hi='135', lev='full', pad='0,0,0,0'); opt.update(a.split('=', 1) for a in sys.argv[4:])
THR, LO, HI = float(opt['thr']), float(opt['lo']), float(opt['hi'])
os.makedirs(out, exist_ok=True)
b = cv2.imread(base); L = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
ps = cv2.imread(subjp, 0) > 127
pt, pb, pl, pr = [int(v) for v in opt['pad'].split(',')]          # black canvas added top,bottom,left,right (px)
if pt or pb or pl or pr:
    L = cv2.copyMakeBorder(L, pt, pb, pl, pr, cv2.BORDER_CONSTANT, value=0)
    ps = cv2.copyMakeBorder(ps.astype(np.uint8), pt, pb, pl, pr, cv2.BORDER_CONSTANT, value=0) > 0
H, W = L.shape; s = max(H, W) / 9504.0          # scale constants to frame size
# bright objects that touch or sit next to the PS subject (keeps faint tentacles/prey; drops isolated backscatter)
bright = (cv2.GaussianBlur(L, (0, 0), 3 * s) > THR).astype(np.uint8)
n, lab, st, _ = cv2.connectedComponentsWithStats(bright, 8)
near = cv2.dilate(ps.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(61 * s) | 1,) * 2)) > 0
keep = np.zeros(n, bool)
for i in range(1, n):
    if st[i, cv2.CC_STAT_AREA] > 20000 * s * s:
        keep[i] = near[lab == i].any()
extra = keep[lab] & ~ps
subj = ps | extra
subj = cv2.morphologyEx(subj.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(15 * s) | 1,) * 2)) > 0
print(f"PS subject {ps.mean()*100:.2f}%  added {extra.mean()*100:.2f}%  final {subj.mean()*100:.2f}%")
S = subj.astype(np.float32)
ramp = np.clip((L - LO) / (HI - LO), 0, 1)
hp = cv2.GaussianBlur(S * ramp, (0, 0), 1.5 * s)
grown = cv2.dilate(subj.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(41 * s) | 1,) * 2)).astype(np.float32)
fill = 1 - cv2.GaussianBlur(grown, (0, 0), 20 * s)
w = lambda name, a: cv2.imwrite(os.path.join(out, name + ".tif"), np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))
w("ds", 1 - S); w("levels", (1 - S) if opt["lev"] == "bg" else (1 - hp)); w("fill", fill); w("hp", hp)
prev = cv2.resize(np.hstack([S, fill, hp]), None, fx=600 / H, fy=600 / H, interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(out, "masks_prev.jpg"), (prev * 255).astype(np.uint8))
