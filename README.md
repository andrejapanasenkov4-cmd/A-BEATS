# A-BEATS

Windows desktop application for preparing beat videos and publishing them to YouTube.

## Current source release

Version: 1.2.0  
Validated in Linux: 18 pytest tests passed, including FFmpeg MP4 render integration tests at 1920x1080 and 3840x2160.

## Windows build

The Windows installer is built on a Windows runner by the workflow at `.github/workflows/build-windows.yml`.

**Important:** the source files from the release ZIP must be present in this repository before running the workflow. The GitHub Actions workflow cannot build from an empty repository.

1. Download the source ZIP from the ChatGPT conversation.
2. Extract it locally.
3. Upload the *contents* of the `A-BEATS` folder to the root of this repository (keep the `.github/workflows` directory).
4. Open **Actions** → **Build A-BEATS for Windows** → **Run workflow**.
5. Download the `A-BEATS-Windows-x64` artifact from the completed run. It contains the packaged app and, if successful, `Setup.exe`.

## YouTube authorization

Live upload requires the owner's Google Cloud OAuth desktop client configuration and interactive authorization. Do not commit OAuth client secrets, refresh tokens, or credentials to this public repository. The app supports a manual YouTube Studio handoff where direct API publishing is not configured.

## Validation limits

The Linux test suite does not prove that the Windows installer, Windows DPAPI storage, or live YouTube publishing works. Those require a completed Windows Actions run and an authorized test channel.
