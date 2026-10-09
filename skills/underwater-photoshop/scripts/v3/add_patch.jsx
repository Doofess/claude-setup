// arguments[0] = params file, one line: psdPath|patchPng|layerName|outJpg
// Pastes an RGBA patch (same pixel size as the PSD) IN PLACE as a new top layer, saves the PSD, exports a JPEG (q12).
#target photoshop
app.displayDialogs = DialogModes.NO;
var pf = File(arguments[0]); pf.encoding = "UTF-8"; pf.open("r"); var p = pf.read().split(/\r?\n/)[0].split("|"); pf.close();
var log = File(arguments[0] + ".log"); log.encoding = "UTF-8"; log.open("w");
function S(id) { return stringIDToTypeID(id); }
try {
  var doc = app.open(File(p[0]));
  for (var i = doc.layers.length - 1; i >= 0; i--) if (doc.layers[i].name == p[2]) doc.layers[i].remove();   // idempotent
  doc.activeLayer = doc.layers[0];
  var src = app.open(File(p[1]));
  src.selection.selectAll(); src.selection.copy(); src.close(SaveOptions.DONOTSAVECHANGES);
  app.activeDocument = doc;
  var d = new ActionDescriptor(); d.putBoolean(S("inPlace"), true);
  executeAction(S("paste"), d, DialogModes.NO);
  doc.activeLayer.name = p[2];
  doc.save();
  var jd = doc.duplicate("export", true);
  if (jd.bitsPerChannel != BitsPerChannelType.EIGHT) jd.bitsPerChannel = BitsPerChannelType.EIGHT;
  var jo = new JPEGSaveOptions(); jo.quality = 12; jo.embedColorProfile = true;
  jd.saveAs(File(p[3]), jo, true, Extension.LOWERCASE); jd.close(SaveOptions.DONOTSAVECHANGES);
  var b = doc.activeLayer.bounds;
  log.writeln("OK layer bounds " + b[0].as("px") + "," + b[1].as("px") + "," + b[2].as("px") + "," + b[3].as("px"));
  doc.close(SaveOptions.DONOTSAVECHANGES);
} catch (e) {
  log.writeln("ERR " + e + " line " + e.line);
  try { app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
}
log.close();
