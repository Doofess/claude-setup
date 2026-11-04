// Subject-pop pass. arguments[0] = path of a params file, one line:
// psd|outJpg|maskPreviewJpg|subjLift|subjContrast|bgDarken|subjSat|globalVib|globalSat|globalContrast|usmAmount|usmRadius|featherPct
//   subjLift: midtone lift on subject (curve 128 -> 128+lift), subjContrast: S-curve strength on subject (0-20),
//   bgDarken: midtone drop on background (curve 128 -> 128-bgDarken), subjSat: Hue/Sat saturation on subject,
//   globalVib/globalSat: Vibrance layer values, globalContrast: global S-curve strength (0-15),
//   usmAmount (%), usmRadius (px): Unsharp Mask on a stamped copy masked to the subject,
//   featherPct: mask feather as % of the long edge.
// Adds named, toggleable layers on top of the existing stack, saves the PSD in place,
// and exports a flattened 8-bit JPEG (q12) plus a small mask preview. Log: <params>.log
#target photoshop
app.displayDialogs = DialogModes.NO;
app.preferences.rulerUnits = Units.PIXELS;
var pf = File(arguments[0]); pf.encoding = "UTF-8"; pf.open("r"); var line = pf.read().split(/\r?\n/)[0]; pf.close();
var log = File(arguments[0] + ".log"); log.encoding = "UTF-8"; log.open("w");
var p = line.split("|");
var psdPath = p[0], outJpg = p[1], maskJpg = p[2];
var subjLift = +p[3], subjCon = +p[4], bgDark = +p[5], subjSat = +p[6], gVib = +p[7], gSat = +p[8], gCon = +p[9], usmAmt = +p[10], usmRad = +p[11], featherPct = +p[12];

function S(id) { return stringIDToTypeID(id); }
function C(id) { return charIDToTypeID(id); }
function makeCurves(name, pts) {
  var d = new ActionDescriptor(); var r = new ActionReference(); r.putClass(S("adjustmentLayer")); d.putReference(C("null"), r);
  var l = new ActionDescriptor(); l.putString(C("Nm  "), name);
  var c = new ActionDescriptor(); c.putEnumerated(S("presetKind"), S("presetKindType"), S("presetKindCustom"));
  var lst = new ActionList(); var ch = new ActionDescriptor(); var cr = new ActionReference();
  cr.putEnumerated(C("Chnl"), C("Chnl"), C("Cmps")); ch.putReference(C("Chnl"), cr);
  var cl = new ActionList();
  for (var i = 0; i < pts.length; i++) { var pt = new ActionDescriptor(); pt.putDouble(C("Hrzn"), pts[i][0]); pt.putDouble(C("Vrtc"), pts[i][1]); cl.putObject(C("Pnt "), pt); }
  ch.putList(C("Crv "), cl); lst.putObject(C("CrvA"), ch); c.putList(C("Adjs"), lst);
  l.putObject(C("Type"), C("Crvs"), c); d.putObject(C("Usng"), S("adjustmentLayer"), l);
  executeAction(C("Mk  "), d, DialogModes.NO);
}
function makeHueSat(name, sat) {
  var d = new ActionDescriptor(); var r = new ActionReference(); r.putClass(S("adjustmentLayer")); d.putReference(C("null"), r);
  var l = new ActionDescriptor(); l.putString(C("Nm  "), name);
  var hs = new ActionDescriptor(); hs.putEnumerated(S("presetKind"), S("presetKindType"), S("presetKindCustom")); hs.putBoolean(C("Clrz"), false);
  var adjs = new ActionList(); var a = new ActionDescriptor(); a.putInteger(C("H   "), 0); a.putInteger(C("Strt"), sat); a.putInteger(C("Lght"), 0);
  adjs.putObject(C("Hst2"), a); hs.putList(C("Adjs"), adjs);
  l.putObject(C("Type"), C("HStr"), hs); d.putObject(C("Usng"), S("adjustmentLayer"), l);
  executeAction(C("Mk  "), d, DialogModes.NO);
}
function makeVibrance(name, vib, sat) {
  var d = new ActionDescriptor(); var r = new ActionReference(); r.putClass(S("adjustmentLayer")); d.putReference(C("null"), r);
  var l = new ActionDescriptor(); l.putString(C("Nm  "), name);
  var v = new ActionDescriptor(); v.putInteger(S("vibrance"), vib); v.putInteger(C("Strt"), sat);
  l.putObject(C("Type"), S("vibrance"), v); d.putObject(C("Usng"), S("adjustmentLayer"), l);
  executeAction(C("Mk  "), d, DialogModes.NO);
}
function addMaskFromSelection() {
  var d = new ActionDescriptor(); d.putClass(C("Nw  "), C("Chnl"));
  var r = new ActionReference(); r.putEnumerated(C("Chnl"), C("Chnl"), C("Msk ")); d.putReference(C("At  "), r);
  d.putEnumerated(C("Usng"), C("UsrM"), C("RvlS"));
  executeAction(C("Mk  "), d, DialogModes.NO);
}
function selectSubject() {
  var d = new ActionDescriptor(); d.putBoolean(S("sampleAllLayers"), true);
  executeAction(S("autoCutout"), d, DialogModes.NO);
}

try {
  var doc = app.open(File(psdPath));
  var W = doc.width.as("px"), H = doc.height.as("px"), longEdge = Math.max(W, H);
  // idempotent: remove layers/channel from a previous pop run
  for (var i = doc.layers.length - 1; i >= 0; i--) {
    var nm = doc.layers[i].name;
    if (nm.indexOf("Pop - ") == 0 || nm == "maskpreview") doc.layers[i].remove();
  }
  for (var j = doc.channels.length - 1; j >= 0; j--) { if (doc.channels[j].name == "Subject (pop pass)") doc.channels[j].remove(); }
  doc.activeLayer = doc.layers[0];               // top of the existing stack

  // 1) subject selection (AI), feathered, stored for reuse
  selectSubject();
  doc.selection.feather(Math.max(2, Math.round(longEdge * featherPct / 100)));
  var subj = doc.channels.add(); subj.name = "Subject (pop pass)"; doc.selection.store(subj);
  doc.activeChannels = doc.componentChannels;
  doc.selection.deselect();

  // 2) subject sharpening: stamped copy, Unsharp Mask, masked to subject
  doc.selection.selectAll(); doc.selection.copy(true); doc.selection.deselect();
  var sl = doc.paste(); sl.name = "Pop - subject sharpen";
  sl.applyUnSharpMask(usmAmt, usmRad, 2);
  doc.selection.load(subj); addMaskFromSelection(); doc.selection.deselect();

  // 3) background darken (inverse subject)
  if (bgDark > 0) {
    doc.selection.load(subj); doc.selection.invert();
    makeCurves("Pop - background darken", [[0,0],[64, Math.max(0, 64 - bgDark*0.7)],[128, 128 - bgDark],[192, 192 - bgDark*0.6],[255,255]]);
    doc.selection.deselect();
  }
  // 4) subject lift + contrast
  doc.selection.load(subj);
  makeCurves("Pop - subject light/contrast", [[0,0],[64, 64 + subjLift*0.6 - subjCon],[128, 128 + subjLift],[192, Math.min(250, 192 + subjLift*0.5 + subjCon)],[255,255]]);
  doc.selection.deselect();
  // 5) subject saturation
  doc.selection.load(subj); makeHueSat("Pop - subject saturation", subjSat); doc.selection.deselect();
  // 6) global contrast + vibrance
  if (gCon > 0) makeCurves("Pop - global contrast", [[0,0],[64, 64 - gCon],[192, 192 + gCon],[255,255]]);
  makeVibrance("Pop - global vibrance", gVib, gSat);

  // 7) mask preview
  var mp = doc.artLayers.add(); mp.name = "maskpreview";
  var black = new SolidColor(); black.rgb.red = 0; black.rgb.green = 0; black.rgb.blue = 0;
  var white = new SolidColor(); white.rgb.red = 255; white.rgb.green = 255; white.rgb.blue = 255;
  doc.selection.selectAll(); doc.selection.fill(black); doc.selection.load(subj); doc.selection.fill(white); doc.selection.deselect();
  var md = doc.duplicate("mask", true);
  md.resizeImage(UnitValue(900, "px"), null, null, ResampleMethod.BICUBIC);
  if (md.bitsPerChannel != BitsPerChannelType.EIGHT) md.bitsPerChannel = BitsPerChannelType.EIGHT;
  var mo = new JPEGSaveOptions(); mo.quality = 8; md.saveAs(File(maskJpg), mo, true, Extension.LOWERCASE); md.close(SaveOptions.DONOTSAVECHANGES);
  mp.remove();

  // 8) save PSD in place, export JPEG
  doc.save();
  var jd = doc.duplicate("export", true);
  if (jd.bitsPerChannel != BitsPerChannelType.EIGHT) jd.bitsPerChannel = BitsPerChannelType.EIGHT;
  var jo = new JPEGSaveOptions(); jo.quality = 12; jo.embedColorProfile = true;
  jd.saveAs(File(outJpg), jo, true, Extension.LOWERCASE); jd.close(SaveOptions.DONOTSAVECHANGES);
  doc.close(SaveOptions.DONOTSAVECHANGES);
  log.writeln("OK " + outJpg + " " + W + "x" + H);
} catch (e) {
  log.writeln("ERR " + e + " line " + e.line);
  try { app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
}
log.close();
