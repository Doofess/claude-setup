// v3 recipe, stage B. arguments[0] = params file, one line:
//   rawPath|maskDir|outPsd|outJpg|dsRadius|dsThreshold|levelsBlack|hpRadius|hpOpacity
// Rebuilds the DSC02565_edit_v3.psd layer stack on top of a Camera Raw Smart Object:
//   RAW smart object > Backscatter removal (Dust & Scratches) > Darken glow and background (Levels)
//   > Black background (fill) > Detail pop (High Pass, Soft Light). Masks come from masks.py (maskDir\*.tif).
#target photoshop
app.displayDialogs = DialogModes.NO;
app.preferences.rulerUnits = Units.PIXELS;
var pf = File(arguments[0]); pf.encoding = "UTF-8"; pf.open("r"); var p = pf.read().split(/\r?\n/)[0].split("|"); pf.close();
var log = File(arguments[0] + ".log"); log.encoding = "UTF-8"; log.open("w");
var rawPath = p[0], maskDir = p[1], outPsd = p[2], outJpg = p[3];
var dsR = +p[4], dsT = +p[5], levBlack = +p[6], hpR = +p[7], hpOp = +p[8];
function S(id) { return stringIDToTypeID(id); }
function C(id) { return charIDToTypeID(id); }

// put a grayscale TIFF into the active layer's mask (adds a reveal-all mask first if needed)
function setMaskFromFile(doc, path) {
  if (!(doc.activeLayer.kind == LayerKind.LEVELS || doc.activeLayer.kind == LayerKind.SOLIDFILL)) {   // adjustment/fill layers come with a mask
    var d = new ActionDescriptor(); d.putClass(C("Nw  "), C("Chnl"));
    var r = new ActionReference(); r.putEnumerated(C("Chnl"), C("Chnl"), C("Msk ")); d.putReference(C("At  "), r);
    d.putEnumerated(C("Usng"), C("UsrM"), C("RvlA")); executeAction(C("Mk  "), d, DialogModes.NO);
  }
  var md = app.open(File(path)); var mname = md.name;
  md.changeMode(ChangeMode.RGB);
  if (md.bitsPerChannel != doc.bitsPerChannel) md.bitsPerChannel = doc.bitsPerChannel;
  app.activeDocument = doc;
  // target the mask channel, then Apply Image from the mask document (same pixel size)
  var ds = new ActionDescriptor(); var rs = new ActionReference(); rs.putEnumerated(C("Chnl"), C("Chnl"), C("Msk ")); ds.putReference(C("null"), rs);
  ds.putBoolean(C("MkVs"), false); executeAction(C("slct"), ds, DialogModes.NO);
  var a = new ActionDescriptor(); var w = new ActionDescriptor(); var src = new ActionReference();
  src.putEnumerated(C("Chnl"), C("Chnl"), C("RGB ")); src.putEnumerated(C("Lyr "), C("Ordn"), C("Mrgd")); src.putName(C("Dcmn"), mname);
  w.putReference(C("T   "), src); w.putEnumerated(C("Clcl"), C("Clcn"), C("Nrml"));
  a.putObject(C("With"), C("Clcl"), w); executeAction(C("AppI"), a, DialogModes.NO);
  md.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = doc;
  doc.activeChannels = doc.componentChannels;
}
function stampVisible(name) {
  var doc = app.activeDocument;
  doc.selection.selectAll(); doc.selection.copy(true); doc.selection.deselect();
  var l = doc.paste(); l.name = name; return l;
}
function makeLevels(name, black) {
  var d = new ActionDescriptor(); var r = new ActionReference(); r.putClass(S("adjustmentLayer")); d.putReference(C("null"), r);
  var l = new ActionDescriptor(); l.putString(C("Nm  "), name);
  var lv = new ActionDescriptor(); lv.putEnumerated(S("presetKind"), S("presetKindType"), S("presetKindCustom"));
  var lst = new ActionList(); var a = new ActionDescriptor(); var cr = new ActionReference();
  cr.putEnumerated(C("Chnl"), C("Chnl"), C("Cmps")); a.putReference(C("Chnl"), cr);
  var inp = new ActionList(); inp.putInteger(black); inp.putInteger(255); a.putList(C("Inpt"), inp);
  lst.putObject(C("LvlA"), a); lv.putList(C("Adjs"), lst);
  l.putObject(C("Type"), C("Lvls"), lv); d.putObject(C("Usng"), S("adjustmentLayer"), l);
  executeAction(C("Mk  "), d, DialogModes.NO);
}
function makeBlackFill(name) {
  var d = new ActionDescriptor(); var r = new ActionReference(); r.putClass(S("contentLayer")); d.putReference(C("null"), r);
  var l = new ActionDescriptor(); l.putString(C("Nm  "), name);
  var sc = new ActionDescriptor(); var c = new ActionDescriptor(); c.putDouble(C("Rd  "), 0); c.putDouble(C("Grn "), 0); c.putDouble(C("Bl  "), 0);
  sc.putObject(C("Clr "), C("RGBC"), c); l.putObject(C("Type"), S("solidColorLayer"), sc);
  d.putObject(C("Usng"), S("contentLayer"), l); executeAction(C("Mk  "), d, DialogModes.NO);
}

try {
  var od = new ActionDescriptor(); od.putPath(C("null"), File(rawPath)); od.putBoolean(S("smartObject"), true);
  executeAction(C("Opn "), od, DialogModes.NO);
  var doc = app.activeDocument;
  doc.activeLayer.name = "RAW (Camera Raw Smart Object, v3 recipe) - double-click to edit";
  // optional black negative space: p[9] = "top,bottom,left,right" px added to the canvas (masks from masks.py are padded the same way)
  if (p.length > 9 && p[9]) {
    var pd = p[9].split(","); var pt = +pd[0], pb = +pd[1], pl = +pd[2], pr = +pd[3];
    var W0 = doc.width.as("px"), H0 = doc.height.as("px");
    if (pt || pl) doc.resizeCanvas(UnitValue(W0 + pl, "px"), UnitValue(H0 + pt, "px"), AnchorPosition.BOTTOMRIGHT);
    if (pb || pr) doc.resizeCanvas(UnitValue(W0 + pl + pr, "px"), UnitValue(H0 + pt + pb, "px"), AnchorPosition.TOPLEFT);
  }

  // p[10] = comma list of layers to build (default all): ds,levels,fill,hp
  var layers = (p.length > 10 && p[10]) ? "," + p[10] + "," : ",ds,levels,fill,hp,";
  function want(k) { return layers.indexOf("," + k + ",") >= 0; }
  if (want("ds")) {
    var dsl = stampVisible("Backscatter removal (Dust & Scratches)");
    dsl.applyDustAndScratches(dsR, dsT);
    setMaskFromFile(doc, maskDir + "/ds.tif");
  }
  if (want("levels")) {
    makeLevels("Darken glow and background (Levels)", levBlack);
    setMaskFromFile(doc, maskDir + "/levels.tif");
  }
  if (want("fill")) {
    makeBlackFill("Black background (fill)");
    setMaskFromFile(doc, maskDir + "/fill.tif");
  }
  if (want("hp")) {
    var hp = stampVisible("Detail pop (High Pass, Soft Light)");
    hp.applyHighPass(hpR); hp.desaturate();
    hp.blendMode = BlendMode.SOFTLIGHT; hp.opacity = hpOp;
    setMaskFromFile(doc, maskDir + "/hp.tif");
  }

  var o = new PhotoshopSaveOptions(); o.embedColorProfile = true; o.layers = true; o.maximizeCompatibility = true;
  doc.saveAs(File(outPsd), o, false, Extension.LOWERCASE);
  var jd = doc.duplicate("export", true);
  if (jd.bitsPerChannel != BitsPerChannelType.EIGHT) jd.bitsPerChannel = BitsPerChannelType.EIGHT;
  var jo = new JPEGSaveOptions(); jo.quality = 12; jo.embedColorProfile = true;
  jd.saveAs(File(outJpg), jo, true, Extension.LOWERCASE); jd.close(SaveOptions.DONOTSAVECHANGES);
  log.writeln("OK " + outPsd + " " + doc.width.as("px") + "x" + doc.height.as("px"));
  doc.close(SaveOptions.DONOTSAVECHANGES);
} catch (e) {
  log.writeln("ERR " + e + " line " + e.line);
  try { app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
}
log.close();
