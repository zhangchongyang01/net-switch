# -*- coding: utf-8 -*-
"""
网络切换器 · 有线 / WiFi

图形界面壳，实际切换逻辑全部在 NetSwitch.ps1 里。
运行需要管理员权限，未提权时会自动请求 UAC 并重启自己。
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

APP_TITLE = "网络切换器 · 有线 / WiFi"


def base_dir() -> str:
    """兼容 PyInstaller 单文件打包后的资源路径。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


HERE = base_dir()
PS1 = os.path.join(HERE, "NetSwitch.ps1")
PS_EXE = os.path.join(
    os.environ.get("WINDIR", r"C:\Windows"),
    "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
)

MARKER = re.compile(r"<<<NS:([A-Za-z0-9+/=]+):NS>>>")


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate_and_exit() -> None:
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, ""
    else:
        exe, params = sys.executable, '"' + os.path.abspath(__file__) + '"'
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    if rc <= 32:
        ctypes.windll.user32.MessageBoxW(
            0,
            "本工具需要管理员权限才能修改网络配置，提权被取消。",
            APP_TITLE,
            0x10,
        )
    sys.exit(0)


def run_ps(*args: str) -> dict:
    if not os.path.isfile(PS1):
        raise RuntimeError("找不到 NetSwitch.ps1，请把两个文件放在同一个目录。")
    cmd = [
        PS_EXE,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", PS1,
        *args,
        "-JsonB64",
    ]
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("核心脚本执行超时（30 秒），请重试。")
    text = (p.stdout or b"").decode("utf-8", errors="replace")
    m = MARKER.search(text)
    if not m:
        raise RuntimeError("核心脚本没有返回有效结果：\n" + text.strip()[:500])
    data = json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
    ads = data.get("adapters")
    if isinstance(ads, dict):
        data["adapters"] = [ads]
    elif not isinstance(ads, list):
        data["adapters"] = []
    return data


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("860x620")
        self.minsize(800, 520)
        self.option_add("*Font", ("Microsoft YaHei UI", 10))

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=27)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure(
            "Go.TButton",
            foreground="#ffffff",
            background="#2f6feb",
            font=("Microsoft YaHei UI", 10, "bold"),
            padding=6,
        )
        style.map(
            "Go.TButton",
            background=[("active", "#2559c4"), ("disabled", "#9bb8ee")],
        )

        self.adapters: list[dict] = []
        self.active_index = 0
        self.hard_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.log("已获取管理员权限，工具就绪。")
        self.refresh()

    def _build_ui(self):
        top = ttk.Frame(self, padding=(16, 14, 16, 6))
        top.pack(fill="x")
        ttk.Label(top, text="网络切换器",
                  font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        self.active_var = tk.StringVar(value="正在读取网络状态…")
        ttk.Label(top, textvariable=self.active_var,
                  font=("Microsoft YaHei UI", 11)).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            top,
            text="原理：把选中的网卡接口跃点数固定为 5、其它网卡设为 200，并关闭「自动跃点」，Windows 的默认路由就会跟着切换。",
            foreground="#666666",
            wraplength=810,
        ).pack(anchor="w", pady=(6, 0))

        mid = ttk.Frame(self, padding=(16, 10, 16, 4))
        mid.pack(fill="both", expand=True)
        cols = ("name", "kind", "status", "ip", "gw", "metric", "auto")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings",
                                 selectmode="browse", height=9)
        heads = {
            "name": ("网卡名称", 160),
            "kind": ("类型", 70),
            "status": ("状态", 110),
            "ip": ("IP 地址", 140),
            "gw": ("默认网关", 140),
            "metric": ("跃点数", 75),
            "auto": ("跃点模式", 100),
        }
        for c in cols:
            label, width = heads[c]
            self.tree.heading(c, text=label)
            self.tree.column(
                c, width=width,
                anchor="w" if c in ("name", "ip", "gw") else "center",
            )
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("active", background="#dff0d8",
                                foreground="#1b5e20")
        self.tree.tag_configure("off", foreground="#999999")
        self.tree.bind("<Double-1>", lambda _e: self.do_use())

        bar = ttk.Frame(self, padding=(16, 4, 16, 2))
        bar.pack(fill="x")
        ttk.Button(bar, text="一键切换（有线 / WiFi）", style="Go.TButton",
                   command=self.do_switch).pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="设为优先", command=self.do_use).pack(side="left", padx=4)
        ttk.Button(bar, text="恢复自动", command=self.do_reset).pack(side="left", padx=4)
        ttk.Button(bar, text="禁用 / 启用", command=self.do_power).pack(side="left", padx=4)
        ttk.Button(bar, text="刷新",
                   command=lambda: self.refresh("手动刷新")).pack(side="left", padx=4)

        opt = ttk.Frame(self, padding=(16, 4, 16, 2))
        opt.pack(fill="x")
        ttk.Checkbutton(
            opt,
            variable=self.hard_var,
            text="彻底模式：切换时同时禁用另一张网卡（会短暂断网，需用「恢复自动」还原）",
        ).pack(anchor="w")

        logf = ttk.LabelFrame(self, text=" 操作日志 ", padding=(8, 4))
        logf.pack(fill="both", padx=16, pady=(10, 4))
        self.logbox = scrolledtext.ScrolledText(logf, height=7,
                                                font=("Consolas", 9))
        self.logbox.pack(fill="both", expand=True)
        self.logbox.configure(state="disabled")

        foot = ttk.Frame(self, padding=(16, 2, 16, 12))
        foot.pack(fill="x")
        ttk.Label(
            foot,
            text="提示：切换只影响新建连接，已建立的 TCP 连接仍走原网卡；企业内网域名解析异常时重开浏览器即可。",
            foreground="#777777",
            wraplength=810,
        ).pack(anchor="w")

    def log(self, msg: str):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def refresh(self, note: str | None = None):
        try:
            data = run_ps("-List")
        except Exception as e:
            self.log("[错误] 读取网卡信息失败：" + str(e).replace("\n", " "))
            messagebox.showerror("读取失败", str(e)[:600])
            return
        if note:
            self.log(note)
        self.adapters = data.get("adapters", [])
        self.active_index = int(data.get("activeIndex") or 0)

        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for a in self.adapters:
            idx = int(a.get("IfIndex") or 0)
            if idx == self.active_index:
                tags = ("active",)
            elif a.get("Status") != "Up":
                tags = ("off",)
            else:
                tags = ()
            self.tree.insert(
                "", "end", iid=str(idx),
                values=(
                    a.get("Name", ""),
                    a.get("Kind", ""),
                    a.get("Status", ""),
                    a.get("IP", "") or "-",
                    a.get("Gateway", "") or "-",
                    a.get("MetricV4", ""),
                    a.get("AutoMetric", ""),
                ),
                tags=tags,
            )

        act = next(
            (a for a in self.adapters
             if int(a.get("IfIndex") or 0) == self.active_index),
            None,
        )
        if act:
            self.active_var.set(
                "当前出网：{}  ·  {}  ·  {}  ·  网关 {}".format(
                    act.get("Name", ""),
                    act.get("Kind", ""),
                    act.get("IP") or "无 IP",
                    act.get("Gateway") or "-",
                )
            )
        else:
            self.active_var.set("当前出网：未检测到活动默认路由")

    def _find(self, iid: str):
        return next(
            (a for a in self.adapters if str(a.get("IfIndex")) == str(iid)),
            None,
        )

    def _run(self, args: list[str], label: str):
        self.log("→ " + label)
        self.update_idletasks()
        try:
            data = run_ps(*args)
        except Exception as e:
            self.log("[失败] " + str(e).replace("\n", " "))
            messagebox.showerror("操作失败", str(e)[:600])
            return
        msg = str(data.get("message") or "").replace("\n", " ")
        if data.get("ok"):
            self.log("   " + msg)
        else:
            self.log("[失败] " + msg)
            # 日志保留完整诊断（出错行/堆栈），弹窗只显示主错误
            messagebox.showerror("操作失败", msg.split(" | LINE:")[0][:600])
        self.refresh()

    def do_switch(self):
        args = ["-Toggle"]
        if self.hard_var.get():
            if not messagebox.askyesno(
                "确认彻底模式",
                "切换时另一张网卡会被禁用，期间可能短暂断网，"
                "之后需要点「恢复自动」才能还原。\n\n继续？",
            ):
                return
            args.append("-Hard")
        self._run(args, "一键切换（有线 / WiFi）" + (" [彻底]" if "-Hard" in args else ""))

    def do_use(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "先在列表中选中一张网卡（双击行也可以）。")
            return
        a = self._find(sel[0])
        if not a:
            return
        if a.get("Status") != "Up":
            messagebox.showwarning(
                "网卡未连接",
                "「{}」当前状态为 {}，设为优先会导致断网，已取消。".format(
                    a.get("Name", ""), a.get("Status", "")
                ),
            )
            return
        self._run(["-Use", sel[0]], "设为优先：{}".format(a.get("Name", "")))

    def do_reset(self):
        self._run(["-Reset"], "恢复系统自动跃点，并重新启用被禁用的网卡")

    def do_power(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "先在列表中选中一张网卡。")
            return
        a = self._find(sel[0])
        if not a:
            return
        disabling = a.get("Status") != "Disabled"
        if disabling and int(a.get("IfIndex") or 0) == self.active_index:
            if not messagebox.askyesno(
                "确认断开",
                "「{}」是当前正在出网的网卡，禁用后会立即断网。\n\n确定？".format(
                    a.get("Name", "")
                ),
            ):
                return
        args = ["-Disable" if disabling else "-Enable", sel[0]]
        self._run(args, ("禁用：" if disabling else "启用：") + a.get("Name", ""))


if __name__ == "__main__":
    if not is_admin():
        elevate_and_exit()
    App().mainloop()
