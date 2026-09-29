"""uvicorn 启动入口。

Spec1 §0 交付定义：python run.py 启动后，浏览器打开 http://127.0.0.1:8000
可完成「注册 → 登录 → 查看当周技术 → 打分 → 管理员查看数据」全链路。
"""

from __future__ import annotations

import sys
import webbrowser
from threading import Timer

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def _open_browser() -> None:
    try:
        webbrowser.open(URL)
    except Exception:  # noqa: BLE001 —— 打不开浏览器不应影响服务
        pass


def main() -> int:
    # 先做配置校验：缺失关键项时启动即报错退出（Spec1 §3 硬性要求 3）
    try:
        import app.config  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"\n[启动失败] {exc}\n", file=sys.stderr)
        return 1

    import uvicorn

    print(f"\n  AIOneWeek 启动中 …… 稍后会自动打开 {URL}")
    print("  关闭本窗口即可停止服务。\n")
    Timer(1.5, _open_browser).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
