# usage: make_xmp.py settings.json out.xmp   -- writes a Camera Raw sidecar from a flat dict of crs: tags
import json, sys
s = json.load(open(sys.argv[1]))
base = {"Version": "18.7", "ProcessVersion": "15.4", "HasSettings": "True", "AlreadyApplied": "False"}
base.update({k: str(v) for k, v in s.items()})
attrs = "\n   ".join(f'crs:{k}="{v}"' for k, v in base.items())
xmp = f'''<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
   xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   {attrs}/>
 </rdf:RDF>
</x:xmpmeta>
'''
open(sys.argv[2], "w", encoding="utf-8").write(xmp)
