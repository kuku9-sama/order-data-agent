import json
from pathlib import Path

from order_agent.agent import Agent
from order_agent.config import DB_PATH
from order_agent.tools import query

spec = json.loads(Path("evals/cases.json").read_text())
agent = Agent(DB_PATH)
results = []
for n, case in enumerate(spec["cases"]):
    actual = agent.chat(case["question"], str(n))
    passed = actual["status"] == case["status"]
    if case["status"] == "ok":
        expected = query(DB_PATH, case["sql"], case["params"])
        passed = passed and actual["rows"] == expected["rows"]
    results.append({"question": case["question"], "passed": passed, "status": actual["status"]})
report = {
    "mode": "offline",
    "dataset": spec["version"],
    "passed": sum(r["passed"] for r in results),
    "total": len(results),
    "results": results,
    "real_model": "未执行；不可用此结果代表真实模型通过",
}
Path("evals/offline-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(f"离线评测：{report['passed']}/{report['total']}")
raise SystemExit(0 if all(r["passed"] for r in results) else 1)
