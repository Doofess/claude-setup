# compare before/after: any-channel clipping (>=254), per-channel clipping, mean saturation, inside subject mask
import sys, glob, os, cv2, numpy as np
import os
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.environ.get("UW_PROJECT") or os.getcwd()          # the photo folder (ARWs, lightroom, edited)
WORK = os.environ.get("UW_WORK") or os.path.join(PROJECT, ".claude-work")   # previews, masks, backups; safe to delete
pats = sys.argv[1:] or ["*"]
for p in sorted(set(sum([glob.glob(os.path.join(WORK, "pop", q + "_pop.jpg")) for q in pats], []))):
    stem = os.path.basename(p)[:-8]
    b = cv2.imread(os.path.join(WORK, "bak_prepop", stem + ".jpg")); a = cv2.imread(p)
    m = cv2.imread(os.path.join(WORK, "pop", stem + "_mask.jpg"), 0)
    sc = 1600 / max(a.shape[:2]); a = cv2.resize(a, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA); b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    m = cv2.resize(m, (a.shape[1], a.shape[0])) > 128
    def st(x):
        s = x[m]; hsv = cv2.cvtColor(x, cv2.COLOR_BGR2HSV)[m]
        return (s >= 254).any(1).mean() * 100, (s[:, 2] >= 254).mean() * 100, hsv[:, 1].mean(), np.percentile(hsv[:, 1], 99), s.mean()
    sb, sa = st(b), st(a)
    print(f"{stem:45s} mask {m.mean()*100:4.0f}%  clipAny {sb[0]:5.2f}->{sa[0]:5.2f}  clipR {sb[1]:5.2f}->{sa[1]:5.2f}  sat {sb[2]:5.1f}->{sa[2]:5.1f}  sat99 {sb[3]:3.0f}->{sa[3]:3.0f}  lum {sb[4]:5.1f}->{sa[4]:5.1f}")
