// arguments[0] = jobs file (default: jobs_psd.txt beside this script). Lines: srcRaw|outPsd ; opens RAW as a Camera Raw Smart Object (sidecar settings) and saves a PSD.
#target photoshop
app.displayDialogs = DialogModes.NO;
var jobsPath = (typeof arguments !== "undefined" && arguments.length) ? arguments[0] : (File($.fileName).parent + "/jobs_psd.txt");
var jobs = File(jobsPath); jobs.encoding = "UTF-8"; jobs.open("r");
var lines = jobs.read().split(/\r?\n/); jobs.close();
var log = File(jobsPath + ".log"); log.encoding = "UTF-8"; log.open("w");
for (var i = 0; i < lines.length; i++) {
  if (!lines[i]) continue;
  var p = lines[i].split("|");
  try {
    var d = new ActionDescriptor();
    d.putPath(charIDToTypeID("null"), File(p[0]));
    d.putBoolean(stringIDToTypeID("smartObject"), true);
    executeAction(charIDToTypeID("Opn "), d, DialogModes.NO);
    var doc = app.activeDocument;
    doc.activeLayer.name = "RAW (Camera Raw Smart Object) - double-click to edit";
    var o = new PhotoshopSaveOptions(); o.embedColorProfile = true; o.layers = true; o.maximizeCompatibility = true;
    doc.saveAs(File(p[1]), o, false, Extension.LOWERCASE);
    log.writeln("OK " + p[1] + " " + doc.width.as("px") + "x" + doc.height.as("px") + " bits=" + doc.bitsPerChannel + " kind=" + doc.activeLayer.kind);
    doc.close(SaveOptions.DONOTSAVECHANGES);
  } catch (e) { log.writeln("ERR " + p[0] + " :: " + e); try { app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
}
log.close();
