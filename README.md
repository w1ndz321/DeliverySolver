<p align="center">
  <img src="https://img.shields.io/badge/AutoSolver-Agentic%20Delivery%20Optimization-F49D22?style=for-the-badge" alt="AutoSolver"/>
</p>

<h1 align="center">AutoSolver—For Delivery</h1>

<p align="center">
  <strong>利用 Agent 自主求解配送订单-骑手分配问题</strong>
</p>

<p align="center">
  <a href="https://w1ndz321.github.io/DeliverySolver/">项目展示</a> ·
  <a href="https://w1ndz321.github.io/DeliverySolver/demo.html">DEMO</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Frontend-HTML%2FCSS%2FJS-F7DF1E?style=flat-square&logo=javascript&logoColor=111" />
  <img src="https://img.shields.io/badge/LLM-DeepSeek%20Compatible-4B8BBE?style=flat-square" />
  <img src="https://img.shields.io/badge/Deploy-EdgeOne%20Pages-46E3B7?style=flat-square" />
</p>

---

## 项目亮点

### 不是单个算法，而是一个会迭代的求解系统

配送订单分配在不同数据上会呈现不同结构：骑手稀缺、合单丰富、接单意愿低、候选关系密集、局部冲突高。AutoSolver 把求解过程拆成在线闭环和离线闭环：在线 Agent 负责在时间预算内快速选择并运行最合适的策略，离线 Agent 负责复盘日志、做消融实验、沉淀新算法和经验。

### 三个核心能力

| 能力 | 说明 |
|------|------|
| **自动数据分析** | 输入配送数据后，自动提取订单数、骑手数、候选关系、合单比例、意愿分布、冲突密度等画像。 |
| **在线 Agent 求解** | 根据数据画像、本地算法库评分和经验库，选择 Top-K 策略并行运行，在预算内生成当前最优算法策略。|
| **离线 Agent 进化** | 根据在线日志和运行分数自主做消融实验，发现可复用规律，扩展算法库、场景池和经验库。 |
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
  │  pair-rich / sparse-supply / low-willingness / high-conflict /...
  ▼
本地算法库评分
  │  greedy / coverage / pair-aware / local-search / destroy-repair /...
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

```text
/              项目展示页
/demo.html     在线/离线闭环 Demo
/api/health    后端健康检查
```
## License
MIT
