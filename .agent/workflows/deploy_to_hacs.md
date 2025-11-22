---
description: How to deploy the SmartBed component to HACS
---

# Deploy to HACS

Follow these steps to deploy a new version of the SmartBed component to your Home Assistant instance via HACS.

1.  **Bump Version**: Ensure the version in `custom_components/smartbed/manifest.json` has been incremented (e.g., `0.1.1` -> `0.1.2`).

2.  **Commit and Push**:
    ```bash
    git add .
    git commit -m "Bump version to 0.1.2"
    git push
    ```

3.  **Create Release**:
    - Go to the [GitHub Repository](https://github.com/HeLau1337/ha-smartbed-component).
    - Click on **Releases** > **Draft a new release**.
    - **Tag version**: Create a new tag matching your manifest version (e.g., `v0.1.2`).
    - **Release title**: Same as tag (e.g., `v0.1.2`).
    - Click **Publish release**.

4.  **Update in Home Assistant**:
    - Open your Home Assistant instance.
    - Go to **HACS** > **Integrations**.
    - Find **SmartBed**.
    - Click the three dots (⋮) > **Redownload**.
    - Ensure the new version is selected in the dropdown.
    - Click **Download**.

5.  **Restart**:
    - Go to **Settings** > **System** > **Restart Home Assistant**.
