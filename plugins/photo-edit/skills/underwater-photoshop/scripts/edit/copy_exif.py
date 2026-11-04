# usage: copy_exif.py source.jpg target.jpg  -> copies the EXIF segment from source into target (re-saves target at q97, no chroma subsampling)
import sys
from PIL import Image
src, dst = sys.argv[1], sys.argv[2]
exif = Image.open(src).info.get("exif")
im = Image.open(dst); im.load()
im.save(dst, "JPEG", quality=97, exif=exif, subsampling=0)
print("exif bytes:", len(exif) if exif else 0)
