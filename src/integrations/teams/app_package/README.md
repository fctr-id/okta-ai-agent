# Build the Tako AI Teams package

This folder contains everything needed to build the installation ZIP: the Python
builder, manifest template, and Fctr icons. It can be copied independently of the
Tako server. Python 3.10 or newer is sufficient; no package installation, virtual
environment, network access, or secrets are needed to build the ZIP.

**Script location:** `<repository-root>/scripts/build_teams_package.py`. The repository
root is the cloned `okta-ai-agent` folder containing `main.py` and `requirements.txt`.
Keep the repository's `src/integrations/teams/app_package/` folder in place; it supplies the builder and assets.

From the repository root, run:

```console
python scripts/build_teams_package.py
```

If already inside `<repository-root>/scripts/`, run `python build_teams_package.py` instead.
Both commands write to `<repository-root>/src/integrations/teams/app_package/output/`.

Paste the **Application (client) ID** from your Entra app registration when
prompted. Use the same ID configured in your Azure Bot and `TEAMS_CLIENT_ID`.

The script creates `src/integrations/teams/app_package/output/Tako-AI-Teams-<client-id>.zip` and prints its full path.
Upload that ZIP in **Teams → Apps → Manage your apps → Upload an app → Upload a
custom app**. Do not extract it. Your organization's policies must allow the upload.

Before uploading, open **Azure Bot → Settings → Channels**, add **Microsoft Teams**
from **Available Channels**, complete and save its configuration, and confirm it
appears as **Healthy**. A configured messaging endpoint alone is not enough; a
missing Teams channel can cause the **Invalid Bot** installation error.

If you copy this folder separately, run `python build.py` inside that folder.
Its ZIP is written to that folder's `output/` directory.
From the repository root, to build without a prompt or choose where the file goes:

```console
python scripts/build_teams_package.py --client-id YOUR-CLIENT-GUID --output path/to/Tako-AI-Teams.zip
```

The template uses Tako's public repository, Security & Privacy section, and license
as its default developer links. To use your organization's deployment-specific
pages, pass `--website`, `--privacy`, and `--terms` with the appropriate HTTPS URLs,
or edit `manifest.template.json` before building.

The Teams app ID is generated consistently from the client ID. When updating an
existing installation, keep its app ID (`--app-id` can override it) and increase
the manifest's `version` in the template for a new package release. Rebuilding for
the same client ID replaces its previous output ZIP.

`color.png` is 192×192; `outline.png` is white on transparency at 32×32. Their SVG
sources are included and derived from the repository's existing Fctr fingerprint
logo. The ZIP contains only `manifest.json`, `color.png`, and `outline.png`.

Building the package does not create Azure resources or configure Tako. Follow
the Teams setup guide first. Never put a client secret in this folder or package.


App version 0.2.0 enables `supportsFiles` for CSV delivery through the native Teams OneDrive consent flow. Rebuild and upload the updated ZIP when upgrading; the app ID and bot ID stay the same. No Graph file scopes are added.
