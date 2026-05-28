# Backend

后端是一个仅使用 Python 标准库的 Agent 服务，负责静态页面、场景派生、在线求解 API 和离线学习 API。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `app.py` | HTTP 入口，提供前端文件、JSON API；监听部署平台的 `PORT`。 |
| `agent/scenarios.py` | 从 `data/large_seed301.txt` 即时派生压力场景；提取演示数据特征。 |

## API

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 部署健康检查 |
| `GET` | `/api/bootstrap` | 获取在线 Agent 元信息和演示场景 |
| `GET` | `/api/scenarios/{id}` | 即时生成场景并返回分析特征 |
| `POST` | `/api/solve` | 兼容入口：调用在线 Agent 求解场景/输入文本并返回摘要 |
| `POST` | `/api/analyze` | 分析传入的原始输入文本 |
| `POST` | `/api/autosolver/solve` | 调用根级在线 Agent，返回画像、计划、逐策略评分与最终解 |
| `POST` | `/api/autosolver/offline` | 聚合已保存的在线日志，生成诊断并更新规则记忆 |

`/api/autosolver/solve` 接受 `{ "input_text": "...", "time_budget": 2.0, "seed": 0 }`，
或使用 `{ "scenario_id": "low-willingness" }` 求解演示派生场景。它通过隔离子进程调用
`agent/online_agent.py`，避免和历史演示引擎的包命名互相影响。

在线 Agent 不修改代码，只把日志和输出写入 `logs/`、`outputs/`。离线 Agent 读取这些日志，
更新 `logs/rule_memory.json`，并把生成的新策略模块写入经验库旁的 `generated_strategies/`。
设置 `AUTOSOLVER_STATE_DIR=/path/to/state` 后，这些运行状态会统一存入该持久化目录。
