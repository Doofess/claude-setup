// v3 recipe, stage A. arguments[0] = params file, one line: rawPath|outBaseTif|outSubjTif
// Opens the RAW through Camera Raw (sidecar = v3 recipe + crop), runs Select Subject,
// writes the 8-bit base render and the subject mask (white = subject) as TIFFs for mask building.
#target photoshop
app.displayDialogs = DialogModes.NO;
app.preferences.rulerUnits = Units.PIXELS;
var pf = File(arguments[0]); pf.encoding = "UTF-8"; pf.open("r"); var p = pf.read().split(/\r?\n/)[0].split("|"); pf.close();
var log = File(arguments[0] + ".log"); log.encoding = "UTF-8"; log.open("w");
function S(id) { return stringIDToTypeID(id); }
function saveTif(doc, path) {
  var o = new TiffSaveOptions(); o.imageCompression = TIFFEncoding.NONE; o.layers = false; o.embedColorProfile = false;
  doc.saveAs(File(path), o, true, Extension.LOWERCASE);
}
try {
  var doc = app.open(File(p[0]));
  if (doc.bitsPerChannel != BitsPerChannelType.EIGHT) doc.bitsPerChannel = BitsPerChannelType.EIGHT;
  saveTif(doc, p[1]);
  var d = new ActionDescriptor(); d.putBoolean(S("sampleAllLayers"), true);
  executeAction(S("autoCutout"), d, DialogModes.NO);
  var black = new SolidColor(); black.rgb.red = 0; black.rgb.green = 0; black.rgb.blue = 0;
  var white = new SolidColor(); white.rgb.red = 255; white.rgb.green = 255; white.rgb.blue = 255;
  var ch = doc.channels.add(); ch.name = "subj"; doc.selection.store(ch); doc.selection.deselect();
  var lay = doc.artLayers.add(); doc.selection.selectAll(); doc.selection.fill(black);
  doc.selection.load(ch); doc.selection.fill(white); doc.selection.deselect();
  doc.flatten(); doc.changeMode(ChangeMode.GRAYSCALE);
  saveTif(doc, p[2]);
  log.writeln("OK " + doc.width.as("px") + "x" + doc.height.as("px"));
  doc.close(SaveOptions.DONOTSAVECHANGES);
} catch (e) {
  log.writeln("ERR " + e + " line " + e.line);
  try { app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
}
log.close();
