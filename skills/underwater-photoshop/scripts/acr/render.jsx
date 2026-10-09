// arguments[0] = jobs file (default: jobs.txt beside this script). Lines: srcRaw|outJpg|maxEdge(0 = full size)|quality ; opens RAW via Camera Raw (sidecar settings), saves JPEG.
#target photoshop
app.displayDialogs = DialogModes.NO;
app.preferences.rulerUnits = Units.PIXELS;
var jobsPath = (typeof arguments !== "undefined" && arguments.length) ? arguments[0] : (File($.fileName).parent + "/jobs.txt");
var jobs = File(jobsPath); jobs.encoding = "UTF-8"; jobs.open("r");
var lines = jobs.read().split(/\r?\n/); jobs.close();
var log = File(jobsPath + ".log"); log.encoding = "UTF-8"; log.open("w");
for (var i = 0; i < lines.length; i++) {
  if (!lines[i]) continue;
  var p = lines[i].split("|");
  try {
    var doc = app.open(File(p[0]));
    var maxEdge = parseInt(p[2], 10);
    if (maxEdge > 0) {
      var w = doc.width.as("px"), h = doc.height.as("px");
      if (w >= h) doc.resizeImage(UnitValue(maxEdge, "px"), null, null, ResampleMethod.BICUBICSHARPER);
      else doc.resizeImage(null, UnitValue(maxEdge, "px"), null, ResampleMethod.BICUBICSHARPER);
    }
    if (doc.bitsPerChannel != BitsPerChannelType.EIGHT) doc.bitsPerChannel = BitsPerChannelType.EIGHT;
    var o = new JPEGSaveOptions(); o.quality = parseInt(p[3], 10); o.embedColorProfile = true;
    doc.saveAs(File(p[1]), o, true, Extension.LOWERCASE);
    log.writeln("OK " + p[1] + " " + doc.width.as("px") + "x" + doc.height.as("px"));
    doc.close(SaveOptions.DONOTSAVECHANGES);
  } catch (e) { log.writeln("ERR " + p[0] + " :: " + e); try { app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
}
log.close();
