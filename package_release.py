#!/usr/bin/env python3
"""
package_release.py — Package GitHub Release Distribution Assets

Generates release packages:
1. releases/F1Manager24-LiveTimingMod-v1.0.0.zip (for drag-and-drop manual mod installation)
"""
import os
import zipfile
from pathlib import Path

VERSION = "1.0.0"

def create_release_zip():
    repo_dir = Path(__file__).resolve().parent
    releases_dir = repo_dir / "releases"
    releases_dir.mkdir(exist_ok=True)
    
    zip_path = releases_dir / f"F1Manager24-LiveTimingMod-v{VERSION}.zip"
    mod_source = repo_dir / "mods" / "LiveTimingMod"
    
    if not mod_source.exists():
        print(f"[-] Error: Mod source directory not found: {mod_source}")
        return
        
    print(f"[+] Packaging Live Timing Mod: {zip_path.name} ...")
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Preserve ue4ss/Mods/LiveTimingMod structure for direct drop-in extraction
        for root, dirs, files in os.walk(mod_source):
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(mod_source)
                arcname = Path("ue4ss") / "Mods" / "LiveTimingMod" / rel_path
                zf.write(file_path, arcname)
                print(f"  -> {arcname}")
                
        # Include installation readme inside zip
        readme_content = (
            "F1 Manager 2024 — Live Timing Mod v1.0.0\n"
            "========================================\n\n"
            "Installation:\n"
            "Extract the 'ue4ss' folder from this zip into your game binaries directory:\n"
            "<Game_Installation_Directory>\\F1Manager24\\Binaries\\Win64\\\n\n"
            "Prerequisite:\n"
            "Requires UE4SS framework installed in the same Win64 folder:\n"
            "https://github.com/UE4SS-RE/RE-UE4SS/releases\n"
        )
        zf.writestr("README_MOD_INSTALL.txt", readme_content)
        
    print(f"[√] Packaging complete! Release archive at: {zip_path}")

if __name__ == "__main__":
    create_release_zip()
