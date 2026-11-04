# usage: qa.py outdir file1.jpg file2.jpg ...
# Per image: size, clipping (% pixels at 0 / 255 per channel), mean saturation, 99th pct saturation,
# over-sharpening halo score (ratio of strong positive/negative ringing at edges), noise sigma in flat areas,
# sharpness map -> location of sharpest region; writes <stem>_100.jpg: 3 crops (sharpest region, center, darkest corner) at 100%.
import sys, os, cv2, numpy as np
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
print("file\tWxH\tclipLo%\tclipHi%\tsatMean\tsat99\thalo\tnoise\tsharp@best\tbestXY")
for p in sys.argv[2:]:
    im = cv2.imread(p); h, w = im.shape[:2]
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    lo = (im.min(axis=2) <= 2).mean()*100; hi = (im.max(axis=2) >= 253).mean()*100
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV); s = hsv[:,:,1]
    satm, s99 = s.mean(), np.percentile(s, 99)
    # halo: unsharp-mask overshoot. Compare image to its own blurred version at edges.
    gf = g.astype(np.float32); bl = cv2.GaussianBlur(gf, (0,0), 2.0); d = gf - bl
    edges = cv2.Canny(g, 60, 160) > 0
    ring = cv2.dilate(edges.astype(np.uint8), np.ones((7,7),np.uint8)) > 0
    halo = float(np.percentile(np.abs(d[ring]), 95)) if ring.any() else 0
    # noise: std of laplacian in flat 64px blocks, take 10th percentile block std (flat areas)
    lap = cv2.Laplacian(gf, cv2.CV_32F)
    bs = 64; stds = [lap[y:y+bs, x:x+bs].std() for y in range(0, h-bs, bs*4) for x in range(0, w-bs, bs*4)]
    noise = float(np.percentile(stds, 10))
    # sharpness map: local variance of laplacian in 256px tiles -> best tile
    ts = 256; best = (0, 0, 0)
    for y in range(0, h-ts, ts//2):
        for x in range(0, w-ts, ts//2):
            v = lap[y:y+ts, x:x+ts].var()
            if v > best[0]: best = (v, x, y)
    _, bx, by = best
    cx, cy = w//2 - 300, h//2 - 300
    corners = [(0,0),(w-600,0),(0,h-600),(w-600,h-600)]
    dk = min(corners, key=lambda c: g[c[1]:c[1]+600, c[0]:c[0]+600].mean())
    crops = [im[by:by+600, bx:bx+600], im[cy:cy+600, cx:cx+600], im[dk[1]:dk[1]+600, dk[0]:dk[0]+600]]
    crops = [cv2.copyMakeBorder(c, 0, 0, 0, 6, cv2.BORDER_CONSTANT, value=(255,255,255)) for c in crops]
    strip = np.hstack(crops)
    for i, lab in enumerate(["sharpest region", "center", "darkest corner"]):
        cv2.putText(strip, lab, (i*606+6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,255), 2)
    stem = os.path.splitext(os.path.basename(p))[0]
    cv2.imwrite(os.path.join(out, stem + "_100.jpg"), strip, [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(f"{stem}\t{w}x{h}\t{lo:.2f}\t{hi:.2f}\t{satm:.0f}\t{s99:.0f}\t{halo:.1f}\t{noise:.1f}\t{best[0]:.0f}\t{bx},{by}")
