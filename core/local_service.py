"""本地 llama-server 的按需生命周期管理（CLI 与 GUI 共用）。

为什么独立成一层：
    之前这段逻辑写在 main.py 里，GUI 也要用同一套「复用已有实例、退出时只关自己
    拉起的那个」的语义，所以抽出来，避免两处实现慢慢跑偏。

要点：
- 云端提供方模式下**不启动**本地服务，省内存（这是修复「每次启动多个 llama-server」的关键）
- 复用外部已运行的实例：`ensure()` 返回 False 表示「不是本次启动的」，退出时不会去关它
- 启动最长等待 120 秒（加载 9B 模型本身就慢），期间给出可读提示
"""
from __future__ import annotations

import subprocess

from core.llama_start import is_server_running, start_llama_server, stop_llama_server


class LocalService:
    """本地 llama-server 的按需管理（云端提供方模式下可以不启动，省内存）"""

    def __init__(self, mmproj: str | None = None, verbose: bool = True):
        self.mmproj = mmproj
        self.proc: subprocess.Popen | None = None
        self.verbose = verbose

    @property
    def running(self) -> bool:
        return is_server_running()

    @property
    def owned(self) -> bool:
        """当前实例是否由本对象拉起（决定退出时是否要关掉它）"""
        return self.proc is not None

    def ensure(self, require_vision: bool = False) -> bool:
        """确保本地服务在跑；返回「本次调用是否启动了新进程」"""
        if self.running:
            if self.verbose:
                print("本地 llama-server 已在运行，直接复用")
            return False
        self.proc = start_llama_server(self.mmproj, require_vision=require_vision)
        return self.proc is not None

    def stop(self):
        """只关自己拉起的那个实例（复用的外部实例不动）"""
        if self.proc is not None:
            stop_llama_server(self.proc)
            self.proc = None
            if self.verbose:
                print("llama-server 已关闭")
