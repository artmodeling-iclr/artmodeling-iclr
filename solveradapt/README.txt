SolverAdapt — local USD physics editor
======================================

SolverAdapt uses Python and OpenUSD to read and edit USD files on your computer.
The public GitHub Pages website displays the tool, but cannot run its Python
backend. Run this bundle locally to use file selection, scene parsing, and save.

Requirements
------------
- Windows 10 or newer
- 64-bit Python 3.11 and an internet connection for first-time setup

Start
-----
1. Extract this ZIP to a directory on your computer.
2. Double-click setup_solveradapt.bat once to create a virtual environment and
   install the packages in requirements.txt.
3. Double-click run_solveradapt.bat. The command window prints the local URL,
   usually http://127.0.0.1:8001/ui. Open that URL in your browser.
4. Select a local .usd, .usda, or .usdc file. You can use the file picker or
   enter its full path. The editor reads its parts, joints, drives, and physics
   properties. Save writes changes directly to the selected USD file.

Keep the command window open while using SolverAdapt. The service listens only
on your computer's loopback address and does not upload your USD file. Work on
a copy of a USD asset when experimenting with new parameter values.

If the file picker is unavailable, enter a full local path in the path field.
If setup reports that a package cannot be installed, confirm that 64-bit Python
3.11 is installed, then rerun setup_solveradapt.bat.
