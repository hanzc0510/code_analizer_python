#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动 Web 服务器
使用线程方式确保模块正确加载
"""
import sys
import threading
import webbrowser
import time
import uvicorn

sys.path.insert(0, '.')
from web.main import app

def run_server():
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8888,
        log_level="info"
    )

if __name__ == "__main__":
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    print("=" * 60)
    print("代码分析工具 - Web 界面")
    print("=" * 60)
    print("  地址: http://localhost:8888")
    print()
    print("按 Ctrl+C 停止服务器")
    print("=" * 60)

    # 延迟打开浏览器
    def open_browser():
        time.sleep(1.5)
        webbrowser.open("http://localhost:8888")

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n服务器已停止")
