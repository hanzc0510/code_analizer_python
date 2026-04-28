#!/usr/bin/env python3
"""启动 Web 界面"""
import sys
import webbrowser
import time
from pathlib import Path

sys.path.insert(0, '.')

print("=" * 60)
print("代码分析工具 - Web 界面")
print("=" * 60)
print()

# 检查依赖
try:
    import fastapi
    import uvicorn
except ImportError:
    print("安装依赖...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "fastapi", "uvicorn"])
    print()

print("启动服务器...")
print("  地址: http://localhost:8888")
print()
print("按 Ctrl+C 停止服务器")
print("=" * 60)
print()

# 延迟打开浏览器
def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://localhost:8888")

import threading
threading.Thread(target=open_browser, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web.main:app",
        host="0.0.0.0",
        port=8888,
        reload=True,
        log_level="info"
    )
