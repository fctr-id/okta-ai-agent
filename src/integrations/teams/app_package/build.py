"""Build the Tako Teams upload package. Requires only Python's standard library."""
import argparse
import json
from pathlib import Path
import struct
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from uuid import UUID, uuid5, NAMESPACE_URL
from zipfile import ZipFile, ZIP_DEFLATED

PACKAGE_DIR = Path(__file__).resolve().parent


def client_id(value):
    try:
        parsed = UUID(value.strip())
        if parsed.int == 0:
            raise ValueError("Empty GUID")
        return str(parsed)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Enter the Entra Application (client) ID as a valid, nonzero GUID.") from exc


def https_url(value):
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise argparse.ArgumentTypeError("Use a public HTTPS URL")
    return value


def icon_bytes(path, size):
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24 or struct.unpack(">II", data[16:24]) != (size, size):
        raise ValueError(f"{path} must be a {size}x{size} PNG")
    return data


def build_package(*, bot_id, website=None, privacy=None, terms=None, color_icon=None,
                  outline_icon=None, output=None, app_id=None):
    bot_id = client_id(bot_id)
    template = PACKAGE_DIR / "manifest.template.json"
    manifest = json.loads(template.read_text(encoding="utf-8"))
    manifest["id"] = client_id(app_id) if app_id else str(uuid5(NAMESPACE_URL, f"tako-teams:{bot_id}"))
    manifest["bots"][0]["botId"] = bot_id
    for field, override in (("websiteUrl", website), ("privacyUrl", privacy), ("termsOfUseUrl", terms)):
        manifest["developer"][field] = https_url(override if override is not None else manifest["developer"][field])
    color_path = Path(color_icon) if color_icon else PACKAGE_DIR / "color.png"
    outline_path = Path(outline_icon) if outline_icon else PACKAGE_DIR / "outline.png"
    color, outline = icon_bytes(color_path, 192), icon_bytes(outline_path, 32)
    output = (Path(output) if output else PACKAGE_DIR / "output" / f"Tako-AI-Teams-{bot_id}.zip").resolve()
    if output in {template.resolve(), color_path.resolve(), outline_path.resolve(), Path(__file__).resolve()}:
        raise ValueError("Output path must not overwrite a package source file")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a completed ZIP; a failed build must not leave a corrupt upload file.
    with NamedTemporaryFile(dir=output.parent, suffix=".tmp", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with ZipFile(temporary_path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("color.png", color)
            archive.writestr("outline.png", outline)
        temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", "--bot-id", dest="bot_id", type=client_id,
                        help="Entra Application (client) ID; prompts when omitted")
    parser.add_argument("--app-id", type=client_id, help="Existing Teams app GUID; default is stable for the client ID")
    for name in ("website", "privacy", "terms"):
        parser.add_argument(f"--{name}", type=https_url, help="Override the bundled project URL")
    parser.add_argument("--color-icon", help="Optional replacement 192x192 PNG")
    parser.add_argument("--outline-icon", help="Optional replacement 32x32 transparent PNG")
    parser.add_argument("--output", help="Destination ZIP; default: output/Tako-AI-Teams-<client-id>.zip inside the app_package folder")
    args = vars(parser.parse_args(argv))
    try:
        while not args["bot_id"]:
            entered = input("Entra Application (client) ID: ").strip()
            try:
                args["bot_id"] = client_id(entered)
            except argparse.ArgumentTypeError as exc:
                print(exc)
        output = build_package(**args)
    except EOFError:
        parser.error("No client ID provided. Run interactively or pass --client-id YOUR-GUID.")
    except KeyboardInterrupt:
        print("\nPackage build cancelled.")
        return 130
    except (OSError, ValueError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))
    print(f"\nTeams package created:\n{output}")
    print("\nUpload this ZIP in Teams: Apps > Manage your apps > Upload an app > Upload a custom app.")
    print("Do not extract the ZIP. Your Tako server and Azure Bot must already be configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
