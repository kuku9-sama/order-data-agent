import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
out = root / "docs/images"
out.mkdir(exist_ok=True)
for port in (8000, 8501):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"本地端口{port}已被占用，请先停止原有服务再截图。")
checks = []
with tempfile.TemporaryDirectory(prefix="order-ui-") as tmp, open("/tmp/order-ui-capture.log", "w") as log:
    db = Path(tmp) / "synthetic.db"
    subprocess.run(
        [str(root / ".venv/bin/python"), "scripts/manage.py", "generate", "--db", str(db)],
        cwd=root,
        check=True,
    )
    env = os.environ.copy()
    env.update(ORDER_DB=str(db), ORDER_MODEL_MODE="offline", ORDER_ALLOW_EXTERNAL="")
    procs = [
        subprocess.Popen(
            [str(root / ".venv/bin/uvicorn"), "order_agent.api:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=root,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        ),
        subprocess.Popen(
            [
                str(root / ".venv/bin/streamlit"),
                "run",
                "ui/app.py",
                "--server.address",
                "127.0.0.1",
                "--server.port",
                "8501",
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=root,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        ),
    ]
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen("http://127.0.0.1:8000/dataset", timeout=1).read()
                urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("服务未启动")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
                headless=True,
                args=["--no-sandbox"],
            )
            page = browser.new_page(viewport={"width": 1600, "height": 1250}, device_scale_factor=1)
            page.goto("http://127.0.0.1:8501", wait_until="networkidle")
            page.get_by_role("button", name="开始分析 →").wait_for()

            def capture(name):
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(650)
                assert not page.locator('[data-testid="stException"]').count()
                page.set_viewport_size(
                    {
                        "width": 1600,
                        "height": 1600
                        if name in {"sales-ranking", "daily-trend", "shop-comparison"}
                        else 1250,
                    }
                )
                page.screenshot(path=str(out / (name + ".png")), full_page=True)
                page.set_viewport_size({"width": 1600, "height": 1250})

            capture("workspace")
            page.get_by_role("button", name="查看分析 ↗").nth(0).click()
            page.get_by_text("查询返回10行", exact=False).wait_for(timeout=15000)
            page.locator("[data-testid=stVegaLiteChart]").first.wait_for(timeout=15000)
            capture("sales-ranking")
            checks.append("首页推荐问题执行与销售排行图表")
            page.get_by_role("tab", name="查询明细", exact=True).click()
            page.locator("[data-testid=stDataFrame]").first.wait_for()
            with page.expect_download() as download:
                page.get_by_role("button", name="↓ 下载查询结果 CSV").click()
            download.value.save_as(str(Path(tmp) / "result.csv"))
            assert (Path(tmp) / "result.csv").read_text(encoding="utf-8-sig").startswith("label,sales_cents")
            page.get_by_role("tab", name="SQL 与口径", exact=True).click()
            page.locator('[data-testid="stCode"]').wait_for()
            checks.append("结果标签切换、真实CSV下载与SQL查看")
            for q, expected, name in [
                ("收入多少", "请明确要统计销售额", "clarification"),
                ("删除订单", "不支持写入", "query-refused"),
            ]:
                page.get_by_role("textbox", name="输入问题").fill(q)
                page.get_by_role("button", name="开始分析 →").click()
                page.get_by_text(expected, exact=False).wait_for(timeout=15000)
                capture(name)
                checks.append(name)
            for card_index, expected, name in [
                (2, "查询返回28行", "daily-trend"),
                (3, "查询返回3行", "shop-comparison"),
            ]:
                page.get_by_role("button", name="＋ 新建会话", exact=True).click()
                page.get_by_role("button", name="查看分析 ↗").nth(card_index).click()
                page.get_by_text(expected, exact=False).wait_for(timeout=15000)
                page.locator("[data-testid=stVegaLiteChart]").first.wait_for()
                capture(name)
            checks.append("每日趋势28天、店铺净额3个店铺的推荐卡片分组")
            page.get_by_text("导入数据", exact=True).click()
            page.get_by_role("heading", name="导入订单数据", exact=True).wait_for()
            capture("imports")
            assert not page.get_by_role("button", name="确认导入", exact=True).is_enabled()
            page.locator("input[type=file]").nth(0).set_input_files(
                {
                    "name": "products.csv",
                    "mimeType": "text/csv",
                    "buffer": "id,sku,name\n1,SKU001,冲突数据\n".encode(),
                }
            )
            page.get_by_role("button", name="预览并校验", exact=True).click()
            page.get_by_text("导入未完成", exact=False).wait_for(timeout=15000)
            page.locator("input[type=file]").nth(0).set_input_files(
                {
                    "name": "products.csv",
                    "mimeType": "text/csv",
                    "buffer": "id,sku,name\n101,SCREENSHOT101,合成新增商品\n".encode(),
                }
            )
            page.get_by_role("button", name="预览并校验", exact=True).click()
            page.get_by_text("预览通过", exact=False).wait_for(timeout=15000)
            page.get_by_text("我确认将所选文件写入本地数据库", exact=True).click()
            assert page.get_by_role("checkbox", name="我确认将所选文件写入本地数据库").is_checked()
            page.get_by_role("button", name="确认导入", exact=True).click()
            page.get_by_text("导入完成，已创建备份", exact=False).wait_for(timeout=15000)
            overview = json.load(urllib.request.urlopen("http://127.0.0.1:8000/dataset"))
            assert overview["products"] == 101
            checks.append("导入冲突反馈、预览校验、确认写入与概览刷新（隔离合成数据库）")
            page.get_by_text("指标口径", exact=True).click()
            page.get_by_role("heading", name="指标口径", exact=True).wait_for()
            checks.append("指标口径导航")
            page.get_by_text("数据问答", exact=True).click()
            page.get_by_role("button", name="＋ 新建会话", exact=True).click()
            page.get_by_role("button", name="查看分析 ↗").nth(0).wait_for()
            mobile = browser.new_page(
                viewport={"width": 390, "height": 1700}, device_scale_factor=1, is_mobile=True, has_touch=True
            )
            mobile.goto("http://127.0.0.1:8501", wait_until="networkidle")
            mobile.get_by_role("button", name="开始分析 →").wait_for()
            mobile.wait_for_timeout(700)
            assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
            mobile.screenshot(path=str(out / "mobile.png"), full_page=True)
            checks.append("390px移动布局无页面横向溢出")
            browser.close()
        (out / "capture.json").write_text(
            json.dumps(
                {
                    "mode": "offline",
                    "source": "Playwright+系统Chromium，隔离固定种子合成数据库；未调用外部模型",
                    "desktop": [1600, 1250],
                    "result_view": [1600, 1600],
                    "mobile": [390, 1700],
                    "checks": checks,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("浏览器验收通过：" + str(len(checks)) + "组交互；8张运行截图已保存。")
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
