#!/usr/bin/env python3
"""
install_mod.py — F1 Manager 2024 Live Timing Mod 一键安装脚本

用于开源分发：自动检测游戏安装路径，并将 LiveTimingMod 安装至 UE4SS Mods 目录。
"""
import os
import sys
import shutil
import argparse
import winreg
from pathlib import Path
from typing import Optional, List

CANDIDATE_PATHS = [
    r"D:\Games\F1Manager2024",
    r"C:\Program Files (x86)\Steam\steamapps\common\F1 Manager 2024",
    r"D:\SteamLibrary\steamapps\common\F1 Manager 2024",
    r"E:\SteamLibrary\steamapps\common\F1 Manager 2024",
    r"F:\SteamLibrary\steamapps\common\F1 Manager 2024",
]

def find_steam_game_path() -> Optional[Path]:
    """尝试从 Steam 注册表和库文件中定位游戏安装目录"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
        winreg.CloseKey(key)
        
        steam_path = Path(steam_path)
        vdf_file = steam_path / "steamapps" / "libraryfolders.vdf"
        if vdf_file.exists():
            with open(vdf_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            # 简单解析 vdf 中的 "path" 字段
            import re
            for match in re.finditer(r'"path"\s+"([^"]+)"', content):
                lib_path = Path(match.group(1).replace(r"\\", "\\"))
                game_dir = lib_path / "steamapps" / "common" / "F1 Manager 2024"
                if game_dir.exists():
                    return game_dir
    except Exception:
        pass
    return None

def find_game_root(user_input: Optional[str] = None) -> Optional[Path]:
    """定位游戏根目录"""
    if user_input:
        p = Path(user_input).resolve()
        if p.exists():
            return p
        print(f"[!] 指定的路径不存在: {user_input}")

    # 1. 检查注册表 Steam 库
    steam_dir = find_steam_game_path()
    if steam_dir and steam_dir.exists():
        return steam_dir

    # 2. 检查常见预设路径
    for path_str in CANDIDATE_PATHS:
        p = Path(path_str)
        if p.exists() and (p / "F1Manager24" / "Binaries" / "Win64").exists():
            return p

    return None

def install():
    parser = argparse.ArgumentParser(description="F1 Manager 2024 Live Timing Mod Installer")
    parser.add_argument("--game-dir", "-g", help="游戏安装根目录 (例如: D:\\Games\\F1Manager2024)")
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parent
    mod_source = repo_dir / "mods" / "LiveTimingMod"

    if not mod_source.exists():
        print(f"[-] 错误: 未在仓库中找到模组源码: {mod_source}")
        sys.exit(1)

    print("=" * 60)
    print(" F1 Manager 2024 Live Timing Mod 一键安装工具")
    print("=" * 60)

    game_root = find_game_root(args.game_dir)
    if not game_root:
        print("[?] 未能自动找到游戏安装目录。")
        val = input("请输入您的 F1 Manager 2024 游戏根目录路径: ").strip()
        if val:
            game_root = Path(val).resolve()

    if not game_root or not game_root.exists():
        print("[-] 无法继续：无效的游戏根目录。")
        sys.exit(1)

    # 兼容传入 Win64 目录或游戏根目录
    if (game_root / "Binaries" / "Win64").exists():
        win64_dir = game_root / "Binaries" / "Win64"
    elif (game_root / "F1Manager24" / "Binaries" / "Win64").exists():
        win64_dir = game_root / "F1Manager24" / "Binaries" / "Win64"
    elif game_root.name.lower() == "win64":
        win64_dir = game_root
    else:
        print(f"[-] 目录结构不匹配，未找到 F1Manager24/Binaries/Win64: {game_root}")
        sys.exit(1)

    print(f"[+] 找到游戏二进制目录: {win64_dir}")

    ue4ss_dir = win64_dir / "ue4ss"
    ue4ss_mods_dir = ue4ss_dir / "Mods"
    ue4ss_dll = win64_dir / "UE4SS.dll"

    # 检查 UE4SS 是否存在
    if not ue4ss_mods_dir.exists() and not ue4ss_dll.exists():
        print("\n[!] 检测到游戏尚未安装 UE4SS 运行时框架！")
        print("    Live Timing 依赖 UE4SS 来安全读取游戏内存。")
        print("    安装步骤极简：")
        print("    1. 前往 GitHub 下载 UE4SS: https://github.com/UE4SS-RE/RE-UE4SS/releases")
        print("       (推荐下载 UE4SS_v3.x.x.zip 或 UE4SS_Xinput.zip)")
        print(f"    2. 将压缩包解压直接放入: {win64_dir}")
        print("    3. 重新运行本脚本即可！\n")
        sys.exit(1)

    ue4ss_mods_dir.mkdir(parents=True, exist_ok=True)
    target_mod_dir = ue4ss_mods_dir / "LiveTimingMod"

    print(f"[+] 正在将模组部署至: {target_mod_dir}")
    shutil.copytree(mod_source, target_mod_dir, dirs_exist_ok=True)

    # 确保 enabled.txt 存在
    enabled_flag = target_mod_dir / "enabled.txt"
    if not enabled_flag.exists():
        enabled_flag.touch()

    print("\n" + "=" * 60)
    print(" [√] Live Timing 模组安装成功！")
    print("=" * 60)
    print("使用步骤：")
    print(" 1. 启动 F1 Manager 2024 游戏并进入比赛 (Practice / Qualifying / Race)")
    print(" 2. 在本项目终端运行: python main.py")
    print(" 3. 即可在终端实时看到 F1 官方电视转播级实时计时塔 (Live Timing Tower)！")
    print("=" * 60)

if __name__ == "__main__":
    install()
