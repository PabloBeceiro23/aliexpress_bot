Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = scriptDir
shell.Run """" & scriptDir & "\.venv\Scripts\pythonw.exe"" """" & scriptDir & "\run_local.py"""" , 0, False
