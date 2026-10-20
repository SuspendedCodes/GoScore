# Publishing GoScore v1.0

1. Run the test suite from the project root: `python -m unittest discover -s tests`.
2. Build the Windows GUI executable on Windows by double-clicking `BUILD_WINDOWS_EXE.bat`.
3. Test `dist\GoScore.exe` on a Windows PC that does not have Python installed.
4. Test cricket and football workflows and OBS Browser Sources before release.
5. Package the tested executable with the README and third-party notices. Keep `data/` and `output/` outside the executable so updates do not erase user data.
6. Publish the release as `v1.0.0` and attach the archive and its SHA-256 checksum.

The Windows executable must be built on Windows; PyInstaller does not produce Windows executables when run on Linux.
