# Logs

`agent.online_agent` 将每次在线求解的画像、策略计划、得分证据与最终解写入 `logs/runs/`。
`agent.offline_agent` 基于这些证据更新 `rule_memory.json`，并把离线生成策略模块写入经验库旁的
`generated_strategies/`。在线阶段不会修改求解器源代码。
