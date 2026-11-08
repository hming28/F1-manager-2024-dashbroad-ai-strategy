#!/usr/bin/env python3
"""
install_mod.py — F1 Manager 2024 Live Timing Mod Installer

Automated installer for open-source users: detects game installation directory
across Epic Games Store, Steam, and custom drives, and deploys LiveTimingMod
into the UE4SS Mods directory.
"""
import os
import sys
import shutil
import argparse
import winreg
from pathlib import Path
from typing import Optional, List

CANDIDATE_PATHS = [
    # Custom / Direct
    r"D:\Games\F1Manager2024",
    r"C:\Games\F1Manager2024",
    r"E:\Games\F1Manager2024",
    # Epic Games Store
    r"C:\Program Files\Epic Games\F1Manager2024",
    r"D:\Epic Games\F1Manager2024",
    r"E:\Epic Games\F1Manager2024",
    r"C:\Program Files\Epic Games\F1 Manager 2024",
    r"D:\Epic Games\F1 Manager 2024",
    # Steam
    r"C:\Program Files (x86)\Steam\steamapps\common\F1 Manager 2024",
    r"D:\SteamLibrary\steamapps\common\F1 Manager 2024",
    r"E:\SteamLibrary\steamapps\common\F1 Manager 2024",
    r"F:\SteamLibrary\steamapps\common\F1 Manager 2024",
    # Xbox / Game Pass
    r"C:\XboxGames\F1 Manager 2024",
    r"D:\XboxGames\F1 Manager 2024",
]

def find_epic_game_path() -> Optional[Path]:
    """Attempt to locate game installation via Epic Games Launcher manifest items."""
    import json
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    manifests_dir = Path(program_data) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if manifests_dir.exists():
        for item_file in manifests_dir.glob("*.item"):
            try:
                with open(item_file, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    display_name = data.get("DisplayName", "")
                    if "F1" in display_name and "Manager" in display_name and "2024" in display_name:
                        loc = Path(data.get("InstallLocation", ""))
                        if loc.exists() and (loc / "F1Manager24" / "Binaries" / "Win64").exists():
                            return loc
            except Exception:
                pass
    return None

def find_steam_game_path() -> Optional[Path]:
    """Attempt to locate game installation via Steam registry and library folders."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        
        steam_path = Path(steam_path)
        vdf_file = steam_path / "steamapps" / "libraryfolders.vdf"
        if vdf_file.exists():
            with open(vdf_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            import re
            for match in re.finditer(r'"path"\s+"([^"]+)"', content):
                lib_path = Path(match.group(1).replace(r"\\", "\\"))
                game_dir = lib_path / "steamapps" / "common" / "F1 Manager 2024"
                if game_dir.exists() and (game_dir / "F1Manager24" / "Binaries" / "Win64").exists():
                    return game_dir
    except Exception:
        pass
    return None

def find_game_root(user_input: Optional[str] = None) -> Optional[Path]:
    """Locate the root game directory (supporting Epic Games, Steam, and custom paths)."""
    if user_input:
        p = Path(user_input).resolve()
        if p.exists():
            return p
        print(f"[!] Specified path does not exist: {user_input}")

    # 1. Check Epic Games manifest
    epic_dir = find_epic_game_path()
    if epic_dir and epic_dir.exists():
        print(f"[+] Detected Epic Games installation: {epic_dir}")
        return epic_dir

    # 2. Check Steam registry and libraries
    steam_dir = find_steam_game_path()
    if steam_dir and steam_dir.exists():
        print(f"[+] Detected Steam installation: {steam_dir}")
        return steam_dir

    # 3. Check preset common paths
    for path_str in CANDIDATE_PATHS:
        p = Path(path_str)
        if p.exists() and (p / "F1Manager24" / "Binaries" / "Win64").exists():
            return p

    return None

def install():
    parser = argparse.ArgumentParser(description="F1 Manager 2024 Live Timing Mod Installer")
    parser.add_argument("--game-dir", "-g", help="Game installation root directory (e.g. D:\\Games\\F1Manager2024)")
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parent
    mod_source = repo_dir / "mods" / "LiveTimingMod"

    if not mod_source.exists():
        print(f"[-] Error: Mod source directory not found in repository: {mod_source}")
        sys.exit(1)

    print("=" * 60)
    print(" F1 Manager 2024 Live Timing Mod Installer")
    print("=" * 60)

    game_root = find_game_root(args.game_dir)
    if not game_root:
        print("[?] Could not automatically locate the game directory.")
        val = input("Please enter your F1 Manager 2024 game root directory path: ").strip()
        if val:
            game_root = Path(val).resolve()

    if not game_root or not game_root.exists():
        print("[-] Cannot proceed: Invalid game root directory.")
        sys.exit(1)

    # Normalize to Win64 binaries directory
    if (game_root / "Binaries" / "Win64").exists():
        win64_dir = game_root / "Binaries" / "Win64"
    elif (game_root / "F1Manager24" / "Binaries" / "Win64").exists():
        win64_dir = game_root / "F1Manager24" / "Binaries" / "Win64"
    elif game_root.name.lower() == "win64":
        win64_dir = game_root
    else:
        print(f"[-] Directory structure mismatch, missing F1Manager24/Binaries/Win64: {game_root}")
        sys.exit(1)

    print(f"[+] Found game binaries directory: {win64_dir}")

    ue4ss_dir = win64_dir / "ue4ss"
    ue4ss_mods_dir = ue4ss_dir / "Mods"
    ue4ss_dll = win64_dir / "UE4SS.dll"

    # Check if UE4SS is installed
    if not ue4ss_mods_dir.exists() and not ue4ss_dll.exists():
        print("\n[!] UE4SS framework not detected in game directory!")
        print("    Live Timing requires UE4SS to safely extract telemetry.")
        print("    Quick setup:")
        print("    1. Download UE4SS from GitHub: https://github.com/UE4SS-RE/RE-UE4SS/releases")
        print("       (Download UE4SS_v3.x.x.zip or UE4SS_Xinput.zip)")
        print(f"    2. Extract contents directly into: {win64_dir}")
        print("    3. Re-run this installer script!\n")
        sys.exit(1)

    ue4ss_mods_dir.mkdir(parents=True, exist_ok=True)
    target_mod_dir = ue4ss_mods_dir / "LiveTimingMod"

    print(f"[+] Deploying mod to: {target_mod_dir}")
    shutil.copytree(mod_source, target_mod_dir, dirs_exist_ok=True)

    # Ensure enabled.txt exists
    enabled_flag = target_mod_dir / "enabled.txt"
    if not enabled_flag.exists():
        enabled_flag.touch()

    print("\n" + "=" * 60)
    print(" [√] Live Timing Mod installed successfully!")
    print("=" * 60)
    print("How to use:")
    print(" 1. Launch F1 Manager 2024 and enter any session (Practice / Qualifying / Race)")
    print(" 2. In your terminal run: python main.py")
    print(" 3. Watch real-time broadcast-grade F1 Timing Tower telemetry live!")
    print("=" * 60)

if __name__ == "__main__":
    install()
