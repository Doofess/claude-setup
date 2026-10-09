# usage: make_v3_xmp.py out.xmp [k=v ...]  (v=DEL removes a key)  -- Camera Raw sidecar with the DSC02565_edit_v3 recipe (laptop edit), optional overrides
import sys
s = dict(Version="18.7", ProcessVersion="11.0", HasSettings="True", AlreadyApplied="False",
 WhiteBalance="Custom", Temperature="6600", Tint="+26", Exposure2012="+1.75", Contrast2012="+18", Highlights2012="-75",
 Shadows2012="+12", Whites2012="-5", Blacks2012="-35", Texture="+45", Clarity2012="+28", Dehaze="+6", Vibrance="+22", Saturation="+4",
 Sharpness="55", SharpenRadius="+1.0", SharpenDetail="35", SharpenEdgeMasking="45",
 LuminanceSmoothing="22", LuminanceNoiseReductionDetail="50", LuminanceNoiseReductionContrast="0",
 ColorNoiseReduction="30", ColorNoiseReductionDetail="50", ColorNoiseReductionSmoothness="50",
 HueAdjustmentOrange="-4", HueAdjustmentYellow="-10",
 SaturationAdjustmentOrange="+55", SaturationAdjustmentYellow="+38", SaturationAdjustmentBlue="-30",
 SaturationAdjustmentPurple="+15", SaturationAdjustmentMagenta="+10",
 LuminanceAdjustmentOrange="+10", LuminanceAdjustmentBlue="-15",
 AutoLateralCA="1", LensProfileEnable="0", VignetteAmount="0", PostCropVignetteAmount="0",
 DefringePurpleAmount="0", DefringeGreenAmount="0", ToneCurveName2012="Linear",
 CameraProfile="Adobe Standard", HasCrop="False")
for kv in sys.argv[2:]:
    k, v = kv.split("=", 1)
    if v == "DEL": s.pop(k, None)
    else: s[k] = v.replace("_", " ")   # "As_Shot" -> "As Shot" (shell-safe spaces)
attrs = "\n   ".join(f'crs:{k}="{v}"' for k, v in s.items())
open(sys.argv[1], "w", encoding="utf-8").write(f'''<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
   xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   {attrs}/>
 </rdf:RDF>
</x:xmpmeta>
''')
