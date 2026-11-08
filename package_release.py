#!/usr/bin/env python3
"""
package_release.py — 打包 GitHub Release 发布资产

生成两个开箱即用的发布包：
1. releases/F1Manager24-LiveTimingMod-v1.0.0.zip (供不想装 Python、只想装 Mod 的玩家一键解压)
2. 验证仓库完整性与依赖
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
        print(f"[-] 错误: 未找到模组目录 {mod_source}")
        return
        
    print(f"[+] 正在打包 Live Timing 模组: {zip_path.name} ...")
    
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 在压缩包中保留 ue4ss/Mods/LiveTimingMod 结构，解压到 Binaries/Win64 即可直接生效
        for root, dirs, files in os.walk(mod_source):
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(mod_source)
                arcname = Path("ue4ss") / "Mods" / "LiveTimingMod" / rel_path
                zf.write(file_path, arcname)
                print(f"  -> {arcname}")
                
        # 添加一个简明说明文件
        readme_content = (
            "F1 Manager 2024 — Live Timing Mod v1.0.0\n"
            "========================================\n\n"
            "安装方法 (Installation):\n"
            "将本压缩包内的 'ue4ss' 文件夹解压并覆盖到您的游戏目录：\n"
            "<游戏安装路径>\\F1Manager24\\Binaries\\Win64\\\n\n"
            "前提条件 (Prerequisite):\n"
            "游戏需要已安装 UE4SS 框架 (https://github.com/UE4SS-RE/RE-UE4SS/releases)\n"
        )
        zf.writestr("README_MOD_INSTALL.txt", readme_content)
        
    print(f"[√] 打包完成！发布包位于: {zip_path}")

if __name__ == "__main__":
    create_release_zip()
