# 中文订单数据分析助手

面向个人使用与学习的单用户订单分析项目。当前可运行的是**合成数据离线演示**：规则规划器将中文示例问题转换为绑定参数的SQL，经SQLGlot与SQLite授权边界执行，结果用于中文摘要、表格和CSV。它不具备通用大模型理解能力，也没有接入电商平台。

DeepSeek工具调用适配器已提供，真实连通性、最低价模型选择和准确率评测**尚未完成**；不能用离线测试替代真实模型验收。

## 安装与运行

需要Python 3.11和uv。在项目根目录执行：

```bash
uv sync --frozen --python 3.11
uv run python scripts/manage.py generate
uv run python scripts/manage.py templates
bash scripts/start.sh
```

生成器固定种子42，生成100个商品、1000笔订单、2000条明细和部分/多次退款。支付日期覆盖2025年1—2月；固定退款截止为2025-03-15。重复生成会拒绝覆盖。API端口8000，Streamlit端口8501，均仅监听回环地址。退出启动脚本会停止它启动的API；恢复时重跑脚本，已有数据库保留。

示例：`1月商品销售额前10名`、`改成2月前3名`、`店铺1净额前5名`、`按日销售额`、`1月退款排行`、`店铺99销售额`（空结果）、`收入多少`（追问）、`删除订单`（拒绝）。离线模式仅支持有限模板；未识别条件不应当作完整业务分析，实际使用前应核对SQL参数。结果最多200行、页面显示50行，金额列单位为分。

## 指标口径

仅CNY，金额以整数分存储、Decimal展示。已支付有效明细实付为销售额，取消未支付订单排除；有效明细数量为销量。退款按成功完成时间统计。净额采用支付期订单归属口径：该期销售额减截至固定截止日的成功退款。退款先按明细汇总再关联，避免多次退款放大销售额。所有日期为Asia/Shanghai，使用左闭右开区间；退款截止是2025-03-15零点（不含）。未提供成本，不计算利润、手续费或汇率。

## 导入与备份

`data/sample/*.csv`为四类表头模板，字段顺序必须保持一致，UTF-8，整数分，时间必须带`+08:00`。外部订单号和店铺唯一，SKU唯一；每单实付须等于明细合计，累计成功退款不得超过明细实付。单表最多10000行、2MB；API请求还应由本地客户端控制大小。

页面或`POST /imports`默认预览：映射表头并在事务内校验后回滚。正式导入必须明确确认本地处理，先备份到`runtime/backups/`；完全相同记录跳过，主键或业务唯一键冲突报错并整批回滚。真实CSV请放`data/private/`（已忽略），不提交真实数据。离线模式不向外部发送数据。

```bash
uv run python scripts/import_data.py --directory data/private
uv run python scripts/import_data.py --directory data/private --commit
```

恢复：先停止服务，保留当前数据库，再将选定备份复制为`runtime/orders.db`，启动并检查`/ready`与汇总结果。备份包含完整数据，须留在本地。不要对运行中的数据库直接覆盖。

## API与防护

`GET /health`检查进程，`GET /ready`检查数据库，均不调用模型；`POST /chat`接收`question`和`session_id`；`POST /imports`独立事务写入；`POST /model/test`当前返回未配置提示，不代表真实连通性通过。

每次分析建立URI `mode=ro`连接并设置`query_only`。SQLGlot解析单查询，遍历CTE/子查询表引用；SQLite授权回调进一步限制业务表和函数，禁止写入、PRAGMA、系统表、扩展加载。约3秒进度预算、200行及100KB结果预算。LIMIT不是超时控制，SQLite进度回调也不能作为操作系统级内存配额。只用于本地单用户小数据，不应公开为通用SQL服务。

CSV下载对公式前缀转义。应用不持久化问题、SQL结果或密钥日志。错误响应使用追踪编号；输入校验错误由FastAPI处理。

## DeepSeek（待真实验收）

用户确认首次验收预算人民币1元，未调用付费接口。`deepseek-chat`仅为待核验的兼容模型名，**尚未确认当前可用或最低价**。官方价格页访问被策略拒绝，取得当前价格后才能按预算执行。

在安全环境设置中配置`DEEPSEEK_API_KEY`；不要在聊天、仓库或脚本中填写值。确认数据去向后，设置`ORDER_MODEL_MODE=deepseek`与`ORDER_ALLOW_EXTERNAL=yes`再启动API。问题、少量历史SQL及参数、结构和口径会发往`api.deepseek.com`；查询结果由本地代码直接摘要，不发给模型。真实数据问题和参数仍可能敏感，未同意前保持离线。

适配器最多8次工具调用、两次SQL语法纠正、10秒模型请求超时、30秒流程预算，权限拒绝与超时直接停止。`ORDER_MAX_MODEL_CALLS`默认8，是单进程调用数量上限，**不是按人民币计费的硬限制**。取得价格及凭据后需核对供应商账户限额与用量，不可据此宣称1元预算已获得严格保证。默认CI只使用MockTransport。

## 验证

```bash
uv run ruff check .
uv run pytest -q
uv run python scripts/evaluate.py
```

30题离线集：20个可回答问题与独立参考SQL结果比较，5题澄清、5题拒绝。结果见`evals/offline-report.json`。它只覆盖有限中文模板，不代表通用中文、真实模型或真实业务数据准确率。测试及运行证据见[验证记录](docs/验证记录.md)。

## 容器与限制

提供Dockerfile与Compose；开发首选上面的本机启动流程。先在主机生成`runtime/orders.db`，再`docker compose up --build`。API分析数据挂载只读，页面导入在容器模式下禁用；独立`importer`服务具备写入目录，默认仅预览：`docker compose --profile import run --rm importer`。确认后追加命令`python scripts/import_data.py --directory /input --commit`，导入前停止API。仅主机回环地址暴露端口，无认证，不部署公网。构建验证状态见验证记录；不在镜像内置密钥。

更多见[设计与学习](docs/设计与学习.md)、[来源](docs/来源.md)。尚无脱敏真实订单试用、真实模型验收或公网部署；不宣称生产可用。
