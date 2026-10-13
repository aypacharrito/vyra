# Windows setup and identity

VYRA 1.2.1 uses its existing hexagon/V mark consistently in the application,
browser favicon, executable resources, setup window and Windows shortcuts.
The SVG is the editable source; the PNG and multi-size ICO are committed assets.
Build-Release.ps1 generates resources for both Windows executables with pinned
go-winres v0.3.3. Build failures stop publication, including setup test failures.

The native setup window uses Segoe UI, a clear primary action, progress and
visible failure recovery. It installs into the current user's Programs folder.
All console helpers use CREATE_NO_WINDOW and HideWindow. OpenAI credentials,
conversations and projects stay in the existing user-data directory.
`VYRA-Setup.exe --preview` exercises setup without installing anything.
`--preview --auto-update` runs and closes that preview automatically.

Primary implementation references studied:

- [Microsoft window controls](https://learn.microsoft.com/en-us/windows/win32/controls/window-controls)
- [Fluent design principles](https://fluent2.microsoft.design/design-principles)
- [go-winres source and resource examples](https://github.com/tc-hib/go-winres)

The release checks cover payload contents/extraction, silent helper flags,
native icon loading, real offscreen Windows drawing, favicon delivery, Go tests,
Go vet and JavaScript syntax. The visual preview uses the actual setup drawing
code. Updating the installed application also verifies the existing encrypted
connection remains available. Live dictation and read-aloud timing remain
dependent on the browser speech service and voice's boundary support.
