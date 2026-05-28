<p align="center">
  <img src="https://img.shields.io/badge/AutoSolver-Agentic%20Delivery%20Optimization-F49D22?style=for-the-badge" alt="AutoSolver"/>
</p>

<h1 align="center">AutoSolver—For Delivery</h1>

<p align="center">
  <strong>利用 Agent 自主求解配送订单-骑手分配问题</strong>
</p>

<p align="center">
  <a href="https://w1ndz321.github.io/DeliverySolver/">项目展示</a> ·
  <a href="https://autosolver-agent-studio.onrender.com/demo.html">在线 Demo</a> ·
  <a href="./reports/">技术报告</a> ·
  <a href="./DEPLOYMENT.md">部署文档</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.x-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Frontend-HTML%2FCSS%2FJS-F7DF1E?style=flat-square&logo=javascript&logoColor=111" />
  <img src="https://img.shields.io/badge/LLM-DeepSeek%20Compatible-4B8BBE?style=flat-square" />
  <img src="https://img.shields.io/badge/Deploy-Render-46E3B7?style=flat-square" />
  <img src="https://img.shields.io/badge/Demo-large__seed301-F49D22?style=flat-square" />
</p>

---

## 参赛信息

| 项目 | 信息 |
|------|------|
| 赛事 | 待填写 |
| 赛道 | 待填写 |
| 参赛者 | 待填写 |
| 学校 | 待填写 |
| 团队名称 | 待填写 |
| 邮箱 | 待填写 |
| 项目名称 | AutoSolver—For Delivery |

---

## 项目亮点

### 不是单个启发式算法，而是一个会迭代的求解系统

配送订单分配在不同数据上会呈现不同结构：骑手稀缺、合单丰富、接单意愿低、候选关系密集、局部冲突高。AutoSolver 把求解过程拆成在线闭环和离线闭环：在线 Agent 负责在时间预算内快速选择并运行最合适的策略，离线 Agent 负责复盘日志、做消融实验、沉淀新算法和经验。

### 三个核心能力

| 能力 | 说明 |
|------|------|
| **自动数据分析** | 输入配送数据后，自动提取订单数、骑手数、候选关系、合单比例、意愿分布、冲突密度等画像。 |
| **在线 Agent 求解** | 根据数据画像、本地算法库评分和经验库，选择 Top-K 策略并行运行，在预算内生成当前最优 `final_submit.py`。 |
| **离线 Agent 进化** | 根据在线日志和运行分数自主做消融实验，发现可复用规律，扩展算法库、场景池和经验库。 |

### Demo 可信边界

| 情况 | 页面行为 |
|------|----------|
| 配置 DeepSeek API | 在线/离线 Agent 会显示模型名、调用状态和 LLM 输出。 |
| 未配置 API Key | 系统仍可运行，展示规则 fallback 或录制闭环 fallback。 |
| LLM 超时或失败 | 页面明确标注失败原因，不把 fallback 伪装成真实 LLM 调用。 |

---

## 系统架构

```text
数据输入
  │
  ▼
数据分析与特征抽取
  │  订单数 / 骑手数 / 候选关系 / 合单比例 / 意愿分布 / 冲突密度
  ▼
场景判断
  │  pair-rich / sparse-supply / low-willingness / high-conflict
  ▼
本地算法库评分
  │  greedy / coverage / pair-aware / local-search / destroy-repair
  ▼
在线 Agent Top-K 决策
  │  结合数据画像、历史经验和当前策略分数
  ▼
并行运行候选策略
  │
  ▼
生成本轮 final_submit.py
  │
  ├──────────────► 在线返回当前最优代码和分数
  │
  ▼
离线 Agent 消融实验
  │  复盘日志 / 生成新策略 / 对照实验 / 解释提升原因
  ▼
经验库更新
  │  新算法 / 新场景 / 新分类规则 / 新策略选择规则
  ▼
下一次在线 Agent 引用经验库
```

### 在线闭环

在线阶段目标是快速求当前输入数据的可用最优解，不修改源代码。

1. 解析用户上传数据或默认 `large_seed301.txt`。
2. 自动生成数据画像和场景判断。
3. 同步运行本地算法库，得到基础策略分数。
4. 在线 Agent 读取数据画像、策略分数和经验库，选择 Top-K 候选策略。
5. 并行运行候选策略，并在时间预算内做有限参数尝试。
6. 返回当前最优策略、分数、解摘要和本轮生成的 `final_submit.py` 代码。

### 离线闭环

离线阶段目标是让系统变聪明，不追求实时返回。

1. 读取在线日志、数据分析结果和算法运行分数。
2. 生成消融计划，例如调整 pair bonus、willingness 权重、冲突修复范围。
3. 运行新策略或策略变体，并和 baseline 做对照。
4. 如果发现可复用提升，解释为什么有效。
5. 写入 demo 经验库：新算法、新场景、新分类规则、新策略选择规则。
6. 下一次在线 Agent 命中对应场景时，优先引用这些经验。

---

## Demo 与评分说明

Demo 默认使用 `data/large_seed301.txt`，也支持上传其他数据集。当前页面分为数据输入、运行模式、Agent 运行流程和结果展示。在线和离线是两个独立运行模式，不提供“一键完整演示”。

### 三个分数不要混淆

| 分数 | 来源 | 含义 |
|------|------|------|
| `749.63` | 在线 Demo | 在线阶段在 `large_seed301` 上 10 秒预算内选出的当前最优展示策略。 |
| `741.98` | 离线 Demo | 离线生成策略 `offline_pair_reserve_ranker` 的消融展示分。 |
| `653.05` | `final_submit.py` | 当前冻结提交 solver，即 `offline_champion_solver` / `solver/improved_solver.py` 的本地评分。 |

### 默认展示数据集画像

| 指标 | 说明 |
|------|------|
| 数据集 | `large_seed301.txt` |
| 主要场景 | 合单丰富、低接单意愿风险明显 |
| 关键特征 | `pair_bundle_ratio` 高，意愿均值偏低，策略需要同时考虑合单收益和拒单风险 |
| 在线目标 | 快速选出当前预算内最优策略并生成代码 |
| 离线目标 | 复盘策略得分，沉淀可复用的算法和场景经验 |

---

## 算法库

### 初始算法库

| 策略 | 作用 |
|------|------|
| `baseline_greedy` | 按原始 `total_score` 贪心，作为安全基线。 |
| `expected_cost_greedy` | 按意愿修正后的期望成本排序，适合低意愿风险明显的数据。 |
| `gain_greedy` | 优先选择相对未分配罚分收益高的候选。 |
| `coverage_first` | 保护候选少的订单，降低漏单风险。 |
| `scarce_pair` | 对合单候选加权，适合 pair-rich 或骑手紧张场景。 |
| `learned_ranker` | 参数化排序器，供在线调参和离线生成策略复用。 |
| `local_search` | 对合法解做替换、加骑手和合并搜索。 |
| `destroy_repair` | 删除较差局部后做确定性修复。 |

### 离线 Agent 新增算法

| 策略 | 来源 | 说明 |
|------|------|------|
| `offline_champion_solver` | 离线 Agent 自主迭代晋升 | 当前 `final_submit.py` 默认提交路径，`large_seed301` 评分约 `653.05`。 |
| `offline_pair_reserve_ranker` | 离线 Agent 自主迭代得到 | 在 pair-rich 场景中保留高价值合单候选，消融展示分约 `741.98`。 |
| `offline_risk_balanced_repair` | 离线 Agent 自主迭代得到 | 在高风险候选中平衡接单意愿和修复收益。 |
| `offline_scarce_coverage_pair` | 离线 Agent 自主迭代得到 | 面向骑手稀缺但仍有合单空间的场景。 |
| `offline_low_willingness_guard` | 离线 Agent 自主迭代得到 | 面向低意愿拒单风险主导的场景。 |
| `offline_conflict_aware_repair` | 离线 Agent 自主迭代得到 | 面向高冲突密度场景，只对冲突热点做局部修复。 |

---

## 场景池与经验库

### 离线 Agent 新增场景

| 场景 | 触发条件 | 推荐策略 |
|------|----------|----------|
| `pair_rich_low_willingness` | `pair_bundle_ratio >= 0.65` 且 `willingness_mean < 0.38` | `offline_champion_solver / offline_pair_reserve_ranker / local_search` |
| `sparse_supply_pairable` | `courier_task_ratio <= 1.15` 且 `pair_bundle_ratio >= 0.25` | `offline_scarce_coverage_pair / coverage_first / scarce_pair` |
| `rejection_risk_dominant` | `willingness_mean < 0.18` 且低意愿候选占比高 | `offline_low_willingness_guard / expected_cost_greedy` |
| `high_conflict_repair` | `conflict_density >= 0.16` | `offline_conflict_aware_repair / destroy_repair / local_search` |

### 经验如何影响下一次在线 Agent

| 经验 | 在线引用方式 |
|------|--------------|
| 合单比例高时，pair bonus 是主要有效特征。 | 命中 pair-rich 场景时，把 pair-aware 策略插入 Top-K 前列。 |
| 低意愿场景不能只看 `total_score`。 | 策略选择时提高 willingness 权重，优先试跑风险控制策略。 |
| 高冲突数据不适合大范围随机破坏。 | 使用 `offline_conflict_aware_repair` 对冲突热点做局部修复。 |
| 冻结冠军 solver 在 `large_seed301` 上稳定优于在线临时策略。 | 作为提交算法库冠军和在线候选的强基线。 |

这些离线资产是 demo 沙箱中的展示数据，用于说明系统如何从日志、消融和经验库形成可持续进化的闭环；稳定提交路径仍由 `final_submit.py` 控制。

---

## LLM Agent 配置

Demo 页面支持 DeepSeek 兼容接口：

```text
Model: deepseek-v4-flash
Base URL: api.deepseek.com
```

API Key 只保存在浏览器内存中，不写入 `localStorage`，不写入运行日志，也不会出现在后端响应里。没有 API Key 或请求超时时，Demo 会展示规则 fallback 或录制闭环 fallback，并在页面上明确标注调用状态。

---

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 求解器 | Python | 数据解析、特征抽取、算法库、评分器、最终提交入口。 |
| 在线 Agent | Python + LLM API | 根据数据画像和算法分数选择 Top-K 策略。 |
| 离线 Agent | Python + LLM API | 复盘日志、做消融、生成新策略、更新经验库。 |
| 前端 | HTML / CSS / JavaScript | 项目介绍页和交互 Demo，无前端构建依赖。 |
| LLM | DeepSeek compatible API | 支持 `deepseek-v4-flash`，失败时提供透明 fallback。 |
| 部署 | Docker / Render | 推荐同源 Web Service 部署，避免 CORS 和后端地址问题。 |

---

## 快速开始

### 本地运行

```bash
PYTHONDONTWRITEBYTECODE=1 python3 backend/app.py --host 127.0.0.1 --port 8080
```

打开：

| 页面 | 地址 |
|------|------|
| 项目展示 | <http://127.0.0.1:8080/> |
| Demo | <http://127.0.0.1:8080/demo.html> |
| 健康检查 | <http://127.0.0.1:8080/api/health> |

### OJ 提交入口

平台调用：

```python
from final_submit import solve

solution = solve(input_text)
```

`final_submit.py` 不依赖 Web 服务、前端、日志或 LLM API。它默认调用 `solver/improved_solver.py`，异常时回退到模块化基线策略，保证返回合法解。

本地验证 `large_seed301`：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
from pathlib import Path
from final_submit import solve
from solver.parser import parse_problem
from evaluator.judge_local import evaluate_solution

text = Path("data/large_seed301.txt").read_text(encoding="utf-8")
problem = parse_problem(text)
solution = solve(text)
result = evaluate_solution(solution, problem)
print(result.valid, result.score, result.covered_tasks, result.uncovered_tasks)
PY
```

当前验证结果：`valid=True`，score 约 `653.05`，覆盖 `40/40`。

---

## 项目结构

```text
submission/
├── backend/                 # 同源 HTTP 服务、Demo API、LLM 测试接口
├── frontend/                # 项目首页和 Demo 页面
├── agent/                   # 在线 Agent、离线 Agent、规则引擎、录制 fallback
├── analyzer/                # 数据画像、特征抽取和报告生成
├── solver/                  # 初始算法库、改进 solver、解析和评分辅助
├── evaluator/               # 本地合法性和分数评估
├── data/                    # large_seed301 默认数据集
├── logs/                    # 经验库和离线生成策略，运行日志默认不提交
├── reports/                 # 分析报告占位和输出
├── tests/                   # 在线/离线闭环和后端接口测试
├── final_submit.py          # OJ 提交入口
├── Dockerfile
├── render.yaml
└── DEPLOYMENT.md
```

---

## API 摘要

| 方法 | 路径 | 作用 |
|------|------|------|
| `GET` | `/api/health` | 部署健康检查。 |
| `GET` | `/api/datasets/largeseed301` | 获取默认数据集。 |
| `POST` | `/api/datasets/preview` | 上传或预览数据集并返回数据摘要。 |
| `POST` | `/api/autosolver/online-demo` | 运行在线闭环 Demo。 |
| `POST` | `/api/autosolver/offline-demo` | 运行离线闭环 Demo。 |
| `POST` | `/api/llm/test` | 测试 DeepSeek 兼容 LLM 配置。 |

---

## 部署

GitHub Pages 只能托管静态页面，不能运行 Python 后端，因此不能单独承载本项目的交互 Demo。推荐把整个仓库部署为一个同源 Web Service：

```text
/              项目展示页
/demo.html     在线/离线闭环 Demo
/api/*         数据分析、求解、离线学习和 LLM 测试接口
```

### Render

仓库已包含 `render.yaml`，可通过 Render Blueprint 创建服务。部署完成后访问 Render 分配的 `*.onrender.com` 地址。

### Docker

```bash
docker build -t autosolver-agent .
docker run --rm -p 8080:8080 -v autosolver-state:/app/state autosolver-agent
```

更多部署细节见 [DEPLOYMENT.md](./DEPLOYMENT.md)。

---

## 测试

```bash
node --check frontend/demo.js
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

当前测试覆盖：

- 数据解析、数据画像、评分和合法性校验。
- 在线 Agent 选择策略、生成 `final_submit.py` 和 fallback 行为。
- 离线 Agent 从日志到经验库的闭环。
- Demo 上传数据集和默认 `large_seed301` 流程。
- LLM 配置脱敏、错误 key 和超时 fallback。

---

## GitHub 提交注意

不要提交真实 API Key、本地 `.env`、运行日志和缓存文件。`.gitignore` 应排除：

```text
logs/runs/
outputs/*/
reports/*
__pycache__/
```

建议保留：

| 文件或目录 | 原因 |
|------------|------|
| `final_submit.py` | OJ 提交入口。 |
| `solver/` | 可复现的核心算法库。 |
| `agent/` | 在线/离线 Agent 逻辑。 |
| `backend/` | Demo 后端和 API。 |
| `frontend/` | 项目首页和交互 Demo。 |
| `data/large_seed301.txt` | 默认展示数据集。 |
| `logs/rule_memory.json` | 可展示的经验库状态。 |
| `logs/generated_strategies/*.py` | 离线生成策略示例。 |

---

## License

待填写
