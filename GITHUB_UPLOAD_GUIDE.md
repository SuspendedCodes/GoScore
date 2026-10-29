# Upload GoScore to GitHub

This folder is the repository root. It includes the source, tests, packaging specification, and a GitHub Actions workflow that tests the project and builds `GoScore.exe` on a Windows runner.

## Important: the EXE is built by GitHub Actions

This archive does **not** contain a precompiled Windows `.exe`. The current build environment cannot safely produce a native Windows executable. Once these files are in a GitHub repository, GitHub Actions will run the tests and build the EXE on Windows.

## Easiest upload method

1. Create a new empty repository on GitHub (do not add a README or licence there, because this package already contains a README).
2. Extract this ZIP on your PC.
3. Open the new repository page and choose **Add file → Upload files**.
4. Upload the contents of the extracted `GoScore` folder, including the hidden `.github` folder. If the browser upload doesn't preserve hidden folders or nested folders correctly, use GitHub Desktop instead (recommended below).
5. Commit the files to the `main` branch.
6. Open the repository's **Actions** tab and watch **Test and build GoScore for Windows**. The workflow runs tests first, then builds the GUI executable on Windows.
7. When the workflow finishes, open its run and download the `GoScore-Windows-x64` artifact.

## Recommended upload method: GitHub Desktop

1. Install GitHub Desktop and sign in.
2. Create a new repository on your computer in the extracted `GoScore` folder, or clone the empty GitHub repository and copy these files into it.
3. Make sure `.github/workflows/build-windows.yml` is present in the repository.
4. Commit and push to GitHub.
5. Check **Actions** for the test/build result.

## Publish a versioned release

After the workflow passes on `main`, create and push a version tag from a local Git terminal:

```bash
git tag v1.0.1
git push origin v1.0.1
```

The tag triggers the Windows build and attaches `GoScore.exe` to the GitHub Release. Do not publish the release as stable until you have downloaded the EXE and tested it on Windows with OBS.

## Notes

- There is no licence file in this package because no distribution licence has been confirmed. Decide on a licence before accepting external contributions or explicitly authorizing redistribution.
- Match data and generated output folders are excluded by `.gitignore`; do not commit real match data, personal information, API credentials, or production logs.
- GitHub Actions must be enabled for the repository. The release workflow requires write permission to repository contents, which is declared in the workflow.
