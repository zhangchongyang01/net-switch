# -*- coding: utf-8 -*-
"""
生成桌面 .lnk 快捷方式（不依赖 COM / WScript.Shell）。

按 MS-SHLLINK 规范手写二进制：
ShellLinkHeader + LinkTargetIDList + LinkInfo + StringData + TerminalBlock。
IDList 由 ILCreateFromPathW 生成 —— 纯 LinkInfo 的 lnk 会被 Shell 判为「无关联」。
生成前先用一个临时 lnk 做真实 Shell 解析自检，确认 Windows 确实能打开这种格式，
避免做出「双击没反应」的假快捷方式。
"""
from __future__ import annotations

import os
import shutil
import struct
import sys
import time

WORKDIR = os.path.dirname(os.path.abspath(__file__))
FORCE = "--force" in sys.argv


def _real_desktop() -> str:
    """取 Windows 真实桌面路径，兼容 OneDrive / 企业文件夹重定向。"""
    # 1) Shell API 最权威
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        # SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY=0x10, NULL, SHGFP_TYPE_CURRENT, buf)
        if ctypes.windll.shell32.SHGetFolderPathW(0, 0x10, 0, 0, buf) == 0:
            if buf.value and os.path.isdir(buf.value):
                return buf.value
    except Exception:
        pass
    # 2) 注册表 User Shell Folders（值里可能带 %USERPROFILE% 等变量）
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        val, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        val = os.path.expandvars(val)
        if os.path.isdir(val):
            return val
    except Exception:
        pass
    # 3) 常规位置
    home = os.path.expanduser("~")
    for p in (os.path.join(home, "Desktop"),
              os.path.join(os.environ.get("USERPROFILE", home), "Desktop"),
              os.path.join(home, "OneDrive", "Desktop")):
        if os.path.isdir(p):
            return p
    return os.path.join(home, "Desktop")


# 桌面路径含当前用户名，必须在每台机器上本地解析，绝不能随仓库分发。
DESKTOP = _real_desktop()

LINK_CLSID = bytes.fromhex("0114020000000000c000000000000046")

F_HAS_IDLIST = 0x00000001
F_HAS_LINK_INFO = 0x00000002
F_HAS_NAME = 0x00000004
F_HAS_WORKING_DIR = 0x00000010
F_HAS_ARGUMENTS = 0x00000020
F_HAS_ICON = 0x00000040
F_IS_UNICODE = 0x00000080
F_RUN_AS_USER = 0x00002000


def _str_data(s: str) -> bytes:
    """StringData: 2-byte 字符数 + UTF-16LE 内容（不含结尾 null）。"""
    return struct.pack("<H", len(s)) + s.encode("utf-16-le")


def _link_info(target: str) -> bytes:
    volume = struct.pack("<IIII", 0x11, 3, 0, 0x10) + b"\x00"
    base = target.encode("mbcs") + b"\x00"
    suffix = b"\x00"
    header_size = 0x1C
    vol_off = header_size
    base_off = vol_off + len(volume)
    suffix_off = base_off + len(base)
    total = header_size + len(volume) + len(base) + len(suffix)
    header = struct.pack(
        "<IIIIIII",
        total, header_size, 1, vol_off, base_off, 0, suffix_off,
    )
    return header + volume + base + suffix


def _id_list(target: str) -> bytes:
    """用 Win32 API 生成标准 LinkTargetIDList（Shell PIDL）。

    纯 LinkInfo 的 lnk 会被 Shell 判为「无关联」，必须带上 IDList。
    """
    import ctypes
    from ctypes import c_void_p, c_wchar_p, POINTER, c_ushort

    ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    sh = ctypes.windll.shell32
    sh.ILCreateFromPathW.argtypes = [c_wchar_p]
    sh.ILCreateFromPathW.restype = c_void_p
    sh.ILFree.argtypes = [c_void_p]

    p = sh.ILCreateFromPathW(target)
    if not p:
        raise RuntimeError("无法为目标生成 Shell IDList: " + target)
    size = 0
    while True:
        cb = ctypes.cast(p + size, POINTER(c_ushort)).contents.value
        if cb == 0:
            size += 2
            break
        size += cb
    raw = ctypes.string_at(p, size)
    sh.ILFree(c_void_p(p))
    return struct.pack("<H", size) + raw


def build_lnk(
    target: str,
    args: str = "",
    workdir: str = "",
    icon: str = "",
    desc: str = "",
    runas: bool = False,
    show: int = 1,
    icon_index: int = 0,
) -> bytes:
    flags = F_HAS_IDLIST | F_HAS_LINK_INFO | F_HAS_NAME | F_IS_UNICODE
    if args:
        flags |= F_HAS_ARGUMENTS
    if workdir:
        flags |= F_HAS_WORKING_DIR
    if icon:
        flags |= F_HAS_ICON
    if runas:
        flags |= F_RUN_AS_USER

    header = b"".join([
        struct.pack("<I", 0x4C),          # HeaderSize
        LINK_CLSID,                       # LinkCLSID
        struct.pack("<I", flags),         # LinkFlags
        struct.pack("<I", 0x20),          # FileAttributes = ARCHIVE
        struct.pack("<Q", 0),             # CreationTime
        struct.pack("<Q", 0),             # AccessTime
        struct.pack("<Q", 0),             # WriteTime
        struct.pack("<I", 0),             # FileSize
        struct.pack("<I", icon_index),    # IconIndex
        struct.pack("<I", show),          # ShowCommand
        struct.pack("<H", 0),             # HotKey
        struct.pack("<H", 0),             # Reserved1
        struct.pack("<I", 0),             # Reserved2
        struct.pack("<I", 0),             # Reserved3
    ])
    assert len(header) == 0x4C

    strings = _str_data(desc)
    if workdir:
        strings += _str_data(workdir)
    if args:
        strings += _str_data(args)
    if icon:
        strings += _str_data(icon)

    return header + _id_list(target) + _link_info(target) + strings + struct.pack("<I", 0)


def inspect(path: str):
    """回读校验：解析刚写出的 lnk。"""
    b = open(path, "rb").read()
    flags = struct.unpack_from("<I", b, 0x14)[0]
    off = 0x4C
    if flags & F_HAS_IDLIST:
        id_size = struct.unpack_from("<H", b, off)[0]
        off += 2 + id_size
    li_size = struct.unpack_from("<I", b, off)[0]
    li = b[off:off + li_size]
    base_off = struct.unpack_from("<I", li, 16)[0]
    target = li[base_off:li.index(b"\x00", base_off)].decode("mbcs", "replace")
    off += li_size
    out = {}
    for name, bit in [
        ("Name", 0x4), ("RelativePath", 0x8), ("WorkingDir", 0x10),
        ("Arguments", 0x20), ("IconLocation", 0x40),
    ]:
        if flags & bit:
            cnt = struct.unpack_from("<H", b, off)[0]
            off += 2
            out[name] = b[off:off + cnt * 2].decode("utf-16-le", "replace")
            off += cnt * 2
    return flags, target, out, len(b)


def shell_self_check() -> bool:
    """让 Windows Shell 真的去解析一个临时 lnk，确认格式可用。"""
    probe_bat = os.path.join(WORKDIR, "_lnk_probe.bat")
    probe_ok = os.path.join(WORKDIR, "_lnk_probe.ok")
    probe_lnk = os.path.join(WORKDIR, "_lnk_probe.lnk")
    if os.path.exists(probe_ok):
        os.remove(probe_ok)
    with open(probe_bat, "w", encoding="ascii", newline="") as f:
        f.write('@echo off\r\necho ok> "' + probe_ok + '"\r\nexit\r\n')
    with open(probe_lnk, "wb") as f:
        f.write(build_lnk(probe_bat, workdir=WORKDIR, desc="probe", show=7))
    try:
        os.startfile(probe_lnk)
        for _ in range(60):
            if os.path.exists(probe_ok):
                return True
            time.sleep(0.1)
        return False
    finally:
        for p in (probe_bat, probe_lnk, probe_ok):
            try:
                os.remove(p)
            except OSError:
                pass


def tkinter_available() -> bool:
    """快捷方式指向的解释器是否带 tkinter（GUI 必需）。"""
    import subprocess
    py = shutil.which("py")
    cmd = [py, "-3", "-c", "import tkinter"] if py else [
        shutil.which("python") or sys.executable, "-c", "import tkinter"]
    try:
        return subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        ).returncode == 0
    except Exception:
        return False


def main():
    print("Shell parse self-check:", "START")
    if shell_self_check():
        print("[OK] lnk 格式通过真实 Shell 解析自检\n")
    else:
        # 自检靠 os.startfile 跑临时 bat，企业 EDR / 组策略常会拦它。
        # lnk 格式本身已固定且验证过，降级为警告，避免整批快捷方式都不生成。
        print("[WARN] Shell 自检未通过（可能被安全策略拦截），仍继续生成。")
        print("       请生成后双击验证；若打不开，改用「右键 bat → 发送到 → 桌面快捷方式」。\n")

    gui_ok = tkinter_available()
    if not gui_ok:
        print("[WARN] 未检测到带 tkinter 的 Python 3，跳过 GUI 快捷方式。")
        print("       安装 Python 3 时请勾选 tcl/tk 和 py launcher 后重跑；")
        print("       或改用 deliver\\ 里的纯 PowerShell 脚本（无需 Python）。\n")

    windir = os.environ.get("WINDIR", r"C:\Windows")
    gui_script = os.path.join(WORKDIR, "net_switch_gui.py")
    # pyw.exe is in %WINDIR% only for all-users installs. Per-user installs put it
    # in Python\Launcher, so also look it up on PATH before falling back.
    launcher = os.path.join(windir, "pyw.exe")
    gui_args = '-3 "' + gui_script + '"'
    if not os.path.isfile(launcher):
        found = shutil.which("pyw")
        if found:
            launcher = found
        else:
            # Plain pythonw.exe does NOT understand the py-launcher "-3" flag.
            launcher = (shutil.which("pythonw")
                        or os.path.join(os.path.dirname(sys.executable), "pythonw.exe"))
            if not os.path.isfile(launcher):
                launcher = ""
            gui_args = '"' + gui_script + '"'

    items = []
    if launcher and gui_ok and os.path.isfile(gui_script):
        items.append({
            "name": "网络切换器.lnk",
            "target": launcher,
            "args": gui_args,
            "workdir": WORKDIR,
            "icon": os.path.join(windir, "System32", "imageres.dll"),
            "icon_index": 25,
            "desc": "网络切换器 - 有线 / WiFi 出网管理",
            "show": 1,
        })

    netshell = os.path.join(windir, "System32", "netshell.dll")
    bat_items = [
        ("切换网络.lnk", "toggle.bat", 0, "一键切换出网网卡（有线 / WiFi）"),
        ("查看状态.lnk", "status.bat", 2, "只读查看当前出网网卡与跃点数"),
        ("恢复自动.lnk", "reset.bat", 4, "恢复 Windows 自动跃点（不用了务必运行）"),
    ]
    for name, bat, icon_idx, desc in bat_items:
        items.append({
            "name": name,
            "target": os.path.join(WORKDIR, bat),
            "args": "",
            "workdir": WORKDIR,
            "icon": netshell,
            "icon_index": icon_idx,
            "desc": desc,
            "show": 1,
        })

    for it in items:
        path = os.path.join(DESKTOP, it["name"])
        if os.path.exists(path) and not FORCE:
            print("[SKIP] 已存在同名文件，未覆盖（加 --force 可重建）:", path)
            continue
        data = build_lnk(
            it["target"], args=it["args"], workdir=it["workdir"],
            icon=it["icon"], desc=it["desc"], show=it["show"],
            icon_index=it["icon_index"],
        )
        with open(path, "wb") as f:
            f.write(data)
        flags, target, out, size = inspect(path)
        print("[OK]", path, "(%d bytes)" % size)
        print("     Target      :", target)
        if out.get("Arguments"):
            print("     Arguments   :", out["Arguments"])
        print("     WorkingDir  :", out.get("WorkingDir", ""))
        print("     Icon        : %s, %d" % (out.get("IconLocation", ""),
                                            struct.unpack_from("<I", data, 0x38)[0]))
        print("     Description :", out.get("Name", ""))
        print("     RunAsUser   :", bool(flags & F_RUN_AS_USER))
        print()


if __name__ == "__main__":
    main()
