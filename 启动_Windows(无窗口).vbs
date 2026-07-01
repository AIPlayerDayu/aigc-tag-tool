' AIGC label detector / remover  --  Windows launcher (no console window)
' Double-click to start. If nothing happens, use the .bat launcher instead
' (it will tell you whether Python is installed).
Option Explicit
Dim fso, sh, base, server, py
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
base = fso.GetParentFolderName(WScript.ScriptFullName)
server = """" & base & "\src\server.py" & """"

py = "pythonw"
On Error Resume Next
' launch server hidden (0 = hidden window), don't wait
sh.Run py & " " & server, 0, False
WScript.Sleep 1500
' open default browser
sh.Run "http://127.0.0.1:8765/", 1, False
