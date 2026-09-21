Option Explicit

Dim args, inputPath, outputPath, app, doc
Set args = WScript.Arguments
If args.Count <> 2 Then
  WScript.Echo "usage: export_word_pdf.vbs input.docx output.pdf"
  WScript.Quit 2
End If

inputPath = args(0)
outputPath = args(1)
On Error Resume Next
Set app = CreateObject("Word.Application")
If Err.Number <> 0 Then
  Err.Clear
  Set app = CreateObject("KWPS.Application")
End If
If Err.Number <> 0 Or app Is Nothing Then
  WScript.Echo "Microsoft Word or WPS Writer is required"
  WScript.Quit 3
End If
On Error GoTo 0
app.Visible = False
app.DisplayAlerts = 0
Set doc = app.Documents.Open(inputPath, False, True)
doc.Fields.Update
doc.ExportAsFixedFormat outputPath, 17
doc.Close False
app.Quit
WScript.Echo "ok"
