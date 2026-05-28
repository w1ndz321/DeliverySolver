<p align="center">
  <img src="https://img.shields.io/badge/AutoSolver-Agentic%20Delivery%20Optimization-F49D22?style=for-the-badge" alt="AutoSolver"/>
</p>

<h1 align="center">AutoSolver—For Delivery</h1>

<p align="center">
  <strong>利用 Agent 自主求解配送订单-骑手分配问题</strong>
</p>

<p align="center">
  <a href="https://w1ndz321.github.io/DeliverySolver/">项目展示</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Frontend-HTML%2FCSS%2FJS-F7DF1E?style=flat-square&logo=javascript&logoColor=111" />
  <img src="https://img.shields.io/badge/LLM-DeepSeek%20Compatible-4B8BBE?style=flat-square" />
  <img src="https://img.shields.io/badge/Deploy-EdgeOne%20Pages-46E3B7?style=flat-square" />
</p>

---

## 项目亮点

AutoSolver 面向配送订单-骑手分配问题，把求解过程拆成在线闭环和离线闭环：

| 模块 | 作用 |
|------|------|
| 数据分析 | 自动提取订单数、骑手数、候选关系、合单比例、接单意愿、冲突密度等特征。 |
| 在线 Agent | 根据数据画像、本地算法库分数和经验库，选择 Top-K 策略并行运行，输出当前最优算法代码。 |
| 离线 Agent | 根据日志和消融实验扩展算法库、场景池和经验库，让下一次在线决策更准。 |

## 核心流程

```text
输入数据
  -> 数据分析
  -> 场景判断
  -> 本地算法库评分
  -> 在线 Agent 选择 Top-K 策略
  -> 并行运行并诊断分数
  -> 返回最优 final_submit
  -> 离线 Agent 消融迭代
  -> 更新算法库 / 场景池 / 经验库
```

## Demo 分数说明

| 分数 | 来源 | 含义 |
|------|------|------|
| `749.63` | 在线 Demo | `large_seed301` 在线闭环 10 秒预算内的展示最优分。 |
| `741.98` | 离线 Demo | `offline_pair_reserve_ranker` 消融展示分。 |
| `653.05` | `final_submit.py` | 当前冻结提交 solver 的本地评分。 |

## 本地运行

```bash
PYTHONDONTWRITEBYTECODE=1 python3 backend/app.py --host 127.0.0.1 --port 8080
```

```text
/              项目展示页
/demo.html     在线/离线闭环 Demo
/api/health    后端健康检查
```

## 提交入口

```python
from final_submit import solve

solution = solve(input_text)
```

## License

MIT
