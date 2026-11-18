"""InkShift Extension Packager.

Packages the compiled dist/ directory into a standalone portable zip file (inkshift-extension.zip)
allowing users to load the unpacked extension without requiring Node.js or Vite.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
MANIFEST_FILE = DIST_DIR / "manifest.json"
ZIP_OUTPUT = PROJECT_ROOT / "inkshift-extension.zip"


def package_extension(output_path: Path = ZIP_OUTPUT) -> bool:
    """Create a zip archive of the dist/ directory."""
    print("=" * 60)
    print("   InkShift Extension Packager")
    print("=" * 60)

    if not MANIFEST_FILE.exists():
        print(f"[ERROR] Cannot package extension: '{MANIFEST_FILE}' not found.")
        print("Please build the extension first using 'npm run build:extension'.")
        return False

    print(f"[InkShift] Packaging '{DIST_DIR}' -> '{output_path.name}'...")
    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(DIST_DIR):
                for file in files:
                    file_path = Path(root) / file
                    # Relative path within dist
                    arcname = file_path.relative_to(DIST_DIR)
                    zipf.write(file_path, arcname=str(arcname))

        zip_size_kb = output_path.stat().st_size / 1024
        print(f"[SUCCESS] Successfully created '{output_path.name}' ({zip_size_kb:.1f} KB).")
        print(f"Target path: {output_path.resolve()}\n")
        return True
    except Exception as exc:
        print(f"[ERROR] Failed to package extension: {exc}")
        return False


if __name__ == "__main__":
    success = package_extension()
    sys.exit(0 if success else 1)
