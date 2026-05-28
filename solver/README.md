# Solver Kernel

`solver/` 是在线服务与 OJ 可复用的轻量求解内核，不依赖 Web、报告或 LLM API。

| 路径 | 职责 |
| --- | --- |
| `parser.py` | 解析 TSV，建立订单、骑手、bundle 和候选索引。 |
| `scoring.py` | 计算期望成本和 `score_decomposition`。 |
| `validator.py` | 检查任务重叠、骑手复用、非法候选与覆盖情况。 |
| `portfolio.py` | 按计划调用稳定策略并保留逐策略评测证据。 |
| `strategies/` | 在线 Agent 可调用但不会动态修改的稳定算法库。 |
| `improved_solver.py` | 已在公开派生场景验证的冻结 OJ champion。 |
| `generated_strategies/` | 离线 Agent 可写入的学习策略目录，在线只按经验库引用已存在模块。 |

策略返回统一格式：

```python
[("T0001,T0002", ["C001"]), ("T0003", ["C004", "C008"])]
```

`portfolio.py` 始终先运行 `baseline_greedy`。高级策略抛异常、超时被跳过或返回非法输出时，仍有合法基线候选可供选择。
在线 Agent 只运行内存中的有限策略变体，不修改代码；离线 Agent 才会根据日志生成新的策略模块并写入经验库。
