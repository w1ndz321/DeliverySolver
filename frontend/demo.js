const byId = (id) => document.getElementById(id);

const state = {
  snapshot: null,
  defaultSnapshot: null,
  dataset: {
    name: "large_seed301.txt",
    source: "default",
    inputText: ""
  },
  demo: null,
  onlineResult: null,
  traceTotal: 9,
  llmTest: null,
  abortController: null
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[character]));
}

function fmt(value, digits = 2) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return numeric.toLocaleString("zh-CN", {
    maximumFractionDigits: digits,
    minimumFractionDigits: Math.abs(numeric) < 10 ? Math.min(digits, 2) : 0
  });
}

function percent(value, digits = 1) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "--";
  return `${fmt(numeric * 100, digits)}%`;
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function getJSON(url, options) {
  const response = await fetch(withEdgeOnePreviewAuth(url), options);
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch (error) {
    const isHtml = /^\s*</.test(text);
    const message = isHtml
      ? `接口 ${url} 没有返回 JSON。当前后端可能还是旧服务，或该 API 路由未生效。`
      : `接口 ${url} 返回了无法解析的内容。`;
    throw new Error(message);
  }
  if (!response.ok) throw new Error(body.error || `Request failed: ${response.status}`);
  return body;
}

function withEdgeOnePreviewAuth(url) {
  if (!url.startsWith("/api/")) return url;
  const pageParams = new URLSearchParams(window.location.search);
  const edgeParams = [...pageParams.entries()].filter(([key]) => key.startsWith("eo_"));
  if (!edgeParams.length) return url;

  const apiURL = new URL(url, window.location.origin);
  edgeParams.forEach(([key, value]) => {
    if (!apiURL.searchParams.has(key)) apiURL.searchParams.set(key, value);
  });
  return `${apiURL.pathname}${apiURL.search}`;
}

function setStatus(kind, text) {
  const node = byId("run-status");
  node.className = kind;
  node.textContent = text;
}

function resetTrace() {
  byId("trace-count").textContent = `0/${state.traceTotal}`;
}

function resetResults() {
  byId("stage-results").innerHTML = "";
}

function getLLMConfig() {
  return {
    api_key: byId("llm-api-key")?.value.trim() || "",
    model: byId("llm-model")?.value.trim() || "deepseek-v4-flash",
    base_url: normalizeBaseURL(byId("llm-base-url")?.value.trim() || "api.deepseek.com")
  };
}

function getOfflineConfig() {
  return {
    max_iterations: Number(byId("offline-iterations")?.value || 5)
  };
}

function getRunMode() {
  return document.querySelector("input[name='run-mode']:checked")?.value || "online";
}

function getDatasetPayload() {
  if (state.dataset.source === "uploaded" && state.dataset.inputText) {
    return {
      name: state.dataset.name || "uploaded_dataset.txt",
      input_text: state.dataset.inputText
    };
  }
  return {
    name: "large_seed301",
    input_text: ""
  };
}

function setTraceTotal(total) {
  state.traceTotal = total;
  byId("trace-count").textContent = `0/${state.traceTotal}`;
}

function normalizeBaseURL(value) {
  let url = String(value || "api.deepseek.com").trim();
  if (!url.includes("://")) url = `https://${url}`;
  url = url.replace(/\/+$/, "");
  if (!url.endsWith("/chat/completions")) url = `${url}/chat/completions`;
  return url;
}

function setLLMStatus(kind, text, message = "") {
  const status = byId("llm-status");
  if (status) {
    status.className = `llm-status ${kind}`;
    status.textContent = text;
  }
  const node = byId("llm-message");
  if (node) node.textContent = message || "可填 api.deepseek.com；请求时自动补全 /chat/completions。API Key 不写入日志。";
}

function relaxBaseURLInputValidation() {
  const input = byId("llm-base-url");
  if (!input) return;
  input.type = "text";
  input.removeAttribute("pattern");
  input.removeAttribute("required");
  input.removeAttribute("aria-invalid");
}

function llmLabel(decision) {
  if (!decision) return "LLM 状态未知";
  const mode = decision.decision?.decision_mode;
  if (mode === "recorded_agent_fallback" || decision.status === "recorded_fallback") {
    if (decision.used_llm && decision.status === "error") {
      return `${decision.model || "LLM"} 调用失败，展示录制闭环 fallback`;
    }
    return "使用 large_seed301 录制闭环 fallback";
  }
  if (decision.used_llm && decision.status === "ok") {
    return `${decision.model || "LLM"} 已参与决策`;
  }
  if (decision.used_llm && decision.status === "error") {
    return `${decision.model || "LLM"} 调用失败，使用规则 fallback`;
  }
  if (decision.status === "pending") return "离线闭环尚未运行";
  if (mode === "mock_agent") return "未配置 LLM，使用 Mock Agent fallback";
  return "未配置 LLM，使用规则 fallback";
}

function compactLLMError(error) {
  const text = String(error || "");
  if (!text) return "";
  if (/timeout|timed out/i.test(text)) return "请求超时，已切换 fallback";
  if (/401|unauthorized|invalid api key/i.test(text)) return "API Key 无效或未授权";
  if (/404|model/i.test(text)) return "模型或接口地址不可用";
  return text.length > 56 ? `${text.slice(0, 56)}...` : text;
}

function renderLLMStatusBlock(result) {
  const onlineDecision = result.online?.online_agent?.topk_decision || {};
  const offlineDecision = firstOfflineDecision(result);
  return `
    <div class="llm-status-grid">
      ${llmStatusCard("在线 Agent", onlineDecision)}
      ${result.offline ? llmStatusCard("离线消融", offlineDecision) : llmStatusCard("离线消融", { status: "pending", used_llm: false, model: "等待运行" })}
    </div>
  `;
}

function llmStatusCard(label, decision) {
  const status = decision?.status || "not_configured";
  const used = decision?.used_llm === true;
  const mode = decision?.decision?.decision_mode;
  const recorded = mode === "recorded_agent_fallback" || status === "recorded_fallback";
  const brief = recorded ? llmLabel(decision) : compactLLMError(decision?.error) || llmLabel(decision);
  const fallbackLabel = mode === "recorded_agent_fallback" || status === "recorded_fallback"
    ? "录制闭环 fallback"
    : mode === "mock_agent" ? "Mock Agent" : "规则 fallback";
  return `
    <div class="llm-result ${status}">
      <span>${escapeHtml(label)}</span>
      <b>${escapeHtml(used ? (decision.model || "LLM") : fallbackLabel)}</b>
      <p>${escapeHtml(brief)}</p>
    </div>
  `;
}

function renderAgentOutputBlock(result) {
  const rows = [
    ["在线 Agent", combinedOnlineAgentDecision(result.online?.online_agent?.topk_decision, result.online?.online_agent?.tuning_decision)],
    ["离线消融", firstOfflineDecision(result)],
  ].filter(([, decision]) => decision);
  return `
    <div class="agent-output-list">
      ${rows.map(([label, decision]) => `
        <details>
          <summary>
            <span>${escapeHtml(label)}</span>
            <b>${escapeHtml(decision.status || "unknown")}</b>
            <em>${escapeHtml(decision.model || "LLM")}</em>
          </summary>
          ${decision.error ? `<p class="agent-error">${escapeHtml(compactLLMError(decision.error))}<br><code>${escapeHtml(decision.error)}</code></p>` : ""}
          ${decision.raw_text ? `<pre><code>${escapeHtml(decision.raw_text)}</code></pre>` : ""}
          <pre><code>${escapeHtml(JSON.stringify(decision.decision || {}, null, 2))}</code></pre>
        </details>
      `).join("")}
    </div>
  `;
}

function firstOfflineDecision(result) {
  const showcaseDecision = result.offline_showcase?.memory_entry?.offline_agent?.ablation_decision
    || result.steps?.find((step) => step.id === "memory")?.showcase?.memory_entry?.offline_agent?.ablation_decision;
  if (showcaseDecision) return showcaseDecision;

  for (const payload of result.memory_details || []) {
    const decision = payload?.offline_agent?.ablation_decision;
    if (decision) return decision;
  }

  const caseTypes = result.offline?.memory?.case_types || {};
  for (const payload of Object.values(caseTypes)) {
    const decision = payload?.offline_agent?.ablation_decision;
    if (decision) return decision;
  }
  return null;
}

async function appendTrace(kind, title, message, index) {
  const node = document.createElement("div");
  node.className = `trace-step ${kind}`;
  node.innerHTML = `
    <i>${String(index).padStart(2, "0")}</i>
    <div>
      <b>${escapeHtml(title)}</b>
      <span>${escapeHtml(message)}</span>
    </div>
  `;
  byId("timeline").appendChild(node);
  byId("timeline").scrollTop = byId("timeline").scrollHeight;
  byId("trace-count").textContent = `${index}/${state.traceTotal}`;
  await sleep(430);
}

function metricCard(label, value, tone = "") {
  return `<div class="metric-card ${tone}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function compactList(items, limit = 3) {
  const values = (items || []).filter(Boolean);
  const visible = values.slice(0, limit);
  const hidden = Math.max(0, values.length - visible.length);
  return `
    <div class="tag-list compact-tags">
      ${visible.map((item) => `<i>${escapeHtml(item)}</i>`).join("") || "<i>--</i>"}
      ${hidden ? `<i>+${hidden}</i>` : ""}
    </div>
  `;
}

function fileName(path) {
  if (!path) return "--";
  return String(path).split("/").filter(Boolean).pop() || path;
}

function dataAnalysisBody(snapshot) {
  const analysis = snapshot.analysis || {};
  const metrics = analysis.metrics || {};
  const profile = snapshot.profile || {};
  const charts = analysis.charts || [];
  const featureTable = analysis.feature_table || [];
  const staticPlan = snapshot.static_plan || {};
  const sceneRules = analysis.scene?.rules || profile.case_label_rules || [];
  const caseType = analysis.scene?.case_type || profile.case_type || "general";
  const matchedRules = sceneRules.filter((rule) => rule.matched).map((rule) => rule.label);
  return `
    <div class="compact-metrics compact-metrics-five">
      ${metricCard("订单", fmt(metrics.orders, 0))}
      ${metricCard("骑手", fmt(metrics.couriers, 0))}
      ${metricCard("候选关系", fmt(metrics.candidates, 0))}
      ${metricCard("合单", percent(metrics.pair_bundle_ratio))}
      ${metricCard("冲突密度", percent(metrics.conflict_density))}
    </div>
    <div class="scene-strip">
      <span>场景判断</span>
      <b>${escapeHtml(caseType)}</b>
      <p>${escapeHtml(analysis.scene?.summary || "暂无场景说明。")}</p>
      ${compactList(matchedRules, 2)}
    </div>
    <details class="stage-detail">
      <summary>展开数据分析详情</summary>
      <div class="analysis-body">
        <div class="analysis-split">
          <div>
            <h3>关键特征</h3>
            <div class="feature-list">
              ${featureTable.slice(0, 8).map((item) => `
                <div>
                  <span>${escapeHtml(item.role)}</span>
                  <b>${escapeHtml(item.name)}</b>
                  <strong>${escapeHtml(formatFeatureValue(item))}</strong>
                </div>
              `).join("")}
            </div>
          </div>
          <div>
            <h3>重要分布</h3>
            <div class="chart-list">
              ${charts.slice(0, 4).map(renderChart).join("")}
            </div>
          </div>
        </div>
        <div class="analysis-summary scene-bottom">
          <span>场景判断</span>
          <b>${escapeHtml(analysis.scene?.case_type || profile.case_type || "general")}</b>
          <p>${escapeHtml(analysis.scene?.summary || "暂无场景说明。")}</p>
          <div class="scene-rule-grid">
            ${sceneRules.map((rule) => `
              <div class="${rule.matched ? "matched" : ""}">
                <strong>${escapeHtml(rule.label)}</strong>
                <em>${rule.matched ? "MATCHED" : "NOT MATCHED"}</em>
                <span>${escapeHtml(rule.metric)}=${escapeHtml(formatFeatureValue({ name: rule.metric, value: rule.value }))} ${escapeHtml(rule.operator)} ${escapeHtml(formatFeatureValue({ name: rule.metric, value: rule.threshold }))}</span>
                <p>${escapeHtml(rule.matched ? rule.reason : "未触发该场景标签。")}</p>
              </div>
            `).join("") || "<div><strong>general</strong><span>无专项规则命中</span><p>使用通用策略池。</p></div>"}
          </div>
          <div class="rule-list">
            ${(staticPlan.matched_rules || []).map((item) => `
              <div><strong>${escapeHtml(item.rule)}</strong><p>${escapeHtml(item.reason)}</p></div>
            `).join("") || "<div><strong>default</strong><p>没有触发专项规则，使用通用策略池。</p></div>"}
          </div>
        </div>
      </div>
    </details>
  `;
}

function renderKnowledge(snapshot) {
  renderAlgorithmLibrary(snapshot.algorithm_library || []);
  renderSceneCatalog(snapshot.scene_catalog || [], snapshot.memory_details || []);
}

function updateDatasetHeader() {
  byId("dataset-name").textContent = state.dataset.name || "large_seed301.txt";
  byId("dataset-source").textContent = state.dataset.source === "uploaded"
    ? "用户上传数据集 · 本次运行使用该文件内容"
    : "默认演示数据集 · 可上传同格式 TSV/TXT 替换";
}

function renderAlgorithmLibrary(items) {
  byId("algorithm-library").className = "library-table";
  byId("algorithm-library").innerHTML = `
    ${renderLibrarySummary(items)}
    <table>
      <thead><tr><th>算法</th><th>来源</th><th>基于</th><th>作用 / 参数</th><th>代码位置</th></tr></thead>
      <tbody>
        ${items.map((item) => `
          <tr>
            <td><b>${escapeHtml(item.name)}</b></td>
            <td>${escapeHtml(formatCatalogSource(item))}</td>
            <td>${escapeHtml(item.base_strategy || item.name)}</td>
            <td>${escapeHtml(item.description)}${item.parameters && Object.keys(item.parameters).length ? `<br><code>${escapeHtml(compactParams(item.parameters))}</code>` : ""}</td>
            <td><code>${escapeHtml(shortPath(item.module_path))}</code></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function catalogBucket(item) {
  if (item.learned_by === "offline_agent_autonomous_iteration" || item.source_label) return "offline";
  if (item.source === "stable_library") return "initial";
  if (item.source === "online_iteration" && item.type === "online_tuning") return "preset";
  if (item.source === "online_iteration" && String(item.type || "").includes("online")) return "generated";
  if (item.type === "offline_generated" || item.source === "offline_generated" || item.source === "learned") return "offline";
  return "other";
}

function renderLibrarySummary(items) {
  const counts = items.reduce((acc, item) => {
    acc[catalogBucket(item)] = (acc[catalogBucket(item)] || 0) + 1;
    return acc;
  }, {});
  return `
    <div class="library-summary">
      <span><b>${counts.initial || 0}</b> 初始内置</span>
      <span><b>${counts.preset || 0}</b> 预置调参</span>
      <span><b>${counts.generated || 0}</b> 本轮生成</span>
      <span><b>${counts.offline || 0}</b> 离线经验</span>
    </div>
  `;
}

function formatCatalogSource(item) {
  const bucket = catalogBucket(item);
  if (item.source_label) return item.source_label;
  const labels = {
    initial: "初始内置",
    preset: "预置调参",
    generated: "本轮生成",
    offline: "离线经验",
    other: formatSource(item.source || item.type)
  };
  return labels[bucket];
}

function formatSource(source) {
  const labels = {
    stable_library: "稳定算法库",
    online_iteration: "在线迭代",
    online_tuning: "在线调参",
    online_generated: "在线生成",
    online_llm_tuned: "LLM 调参",
    offline_generated: "离线沉淀",
    construction: "构造策略",
    refinement: "修复策略"
  };
  return labels[source] || source || "--";
}

function renderSceneCatalog(items, memoryDetails = []) {
  const learnedCards = memoryDetails.map((item) => ({
    id: `${item.case_type} · 经验`,
    condition: `离线日志证据：${fmt(item.evidence_runs, 0)} 次`,
    focus: `有价值特征：${(item.valuable_features || []).map((feature) => feature.name || feature).join(" / ") || "--"}`,
    preferred: item.preferred_strategies || [],
    source: "learned"
  }));
  const cards = [
    ...items.map((item) => ({ ...item, source: "initial" })),
    ...learnedCards,
  ];
  byId("scene-catalog").className = "scene-list";
  byId("scene-catalog").innerHTML = cards.map((item) => `
    <div>
      <strong class="source-badge ${item.source === "learned" ? "learned" : "initial"}">${item.source_label || (item.source === "learned" ? "离线经验" : "初始内置")}</strong>
      <b>${escapeHtml(item.id)}</b>
      <span>${escapeHtml(item.condition)}</span>
      <p>${escapeHtml(item.focus)}</p>
      <em>${escapeHtml((item.preferred || []).join(" / "))}</em>
    </div>
  `).join("");
}

function shortPath(path) {
  if (!path) return "--";
  const marker = "/submission/";
  const index = path.indexOf(marker);
  return index >= 0 ? path.slice(index + marker.length) : path;
}

function formatFeatureValue(item) {
  const value = item.value;
  if (typeof value === "number") {
    if (item.name.includes("ratio") || item.name.includes("density")) return percent(value);
    return fmt(value, 3);
  }
  return value ?? "--";
}

function renderChart(chart) {
  const series = chart.series || [];
  const values = series.map((item) => Number(item.value)).filter(Number.isFinite);
  const max = Math.max(...values.map((value) => Math.abs(value)), 1);
  return `
    <article class="mini-chart">
      <h4>${escapeHtml(chart.title)}</h4>
      ${series.slice(0, 5).map((item) => {
        const value = Number(item.value);
        const width = Number.isFinite(value) ? Math.max(5, Math.abs(value) / max * 100) : 5;
        const display = chart.unit === "ratio" ? percent(value) : fmt(value, 3);
        return `
          <div class="chart-row">
            <span>${escapeHtml(item.label)}</span>
            <i style="--w:${width}%"></i>
            <b>${escapeHtml(display)}</b>
          </div>
        `;
      }).join("")}
    </article>
  `;
}

function scoreRange(outcomes) {
  const scores = outcomes.map((item) => Number(item.score)).filter(Number.isFinite);
  return {
    min: Math.min(...scores),
    max: Math.max(...scores)
  };
}

function stageCard(id, title, summary, body, open = false) {
  const node = document.createElement("article");
  node.className = "stage-card";
  node.innerHTML = `
    <div class="stage-head">
      <span>${escapeHtml(id)}</span>
      <div>
        <h3>${escapeHtml(title)}</h3>
        <p>${escapeHtml(summary)}</p>
      </div>
    </div>
    ${body}
  `;
  byId("stage-results").appendChild(node);
  const detail = node.querySelector("details");
  if (detail) {
    detail.open = open;
    node.classList.add("is-expandable");
    node.querySelector(".stage-head").addEventListener("click", () => {
      detail.open = !detail.open;
    });
  }
}

function renderDataAnalysisStage(snapshot) {
  const caseType = snapshot.analysis?.scene?.case_type || snapshot.profile?.case_type || "general";
  stageCard(
    "01",
    "数据分析完成",
    `识别到 ${caseType} 场景，提取规模、供需、合单、意愿和冲突特征。`,
    dataAnalysisBody(snapshot)
  );
}

function renderLLMStage(result) {
  const hasOffline = Boolean(result.offline);
  stageCard(
    "LLM",
    "DeepSeek Agent 调用状态",
    hasOffline
      ? "展示各阶段是否调用 LLM，以及失败后的 fallback 状态。"
      : "展示在线阶段是否调用 LLM；离线阶段尚未运行。",
    `${renderLLMStatusBlock(result)}${renderAgentOutputBlock(result)}`
  );
}

function renderStrategyPlan(step) {
  const strategies = step.strategies || [];
  const selectedStrategies = step.selected_strategies || [];
  const iterationCandidates = step.iteration_candidates || [];
  const candidateCatalog = step.candidate_catalog || [];
  const memoryHits = step.memory_hits || [];
  const rules = step.matched_rules || [];
  const localScores = step.local_scores || [];
  const topkReasons = step.topk_reasons || [];
  const modeLabel = step.decision_mode === "llm" ? "LLM Agent" : "Mock Agent fallback";
  stageCard(
    "02",
    "本地基准评分与 Top-K 决策",
    step.summary || "先运行本地算法库，再由在线 Agent 选择 Top-K 策略。",
    `
      <div class="decision-strip">
        ${metricCard("决策模式", modeLabel)}
        ${metricCard("本地基准", `${fmt(localScores.length, 0)} 个`)}
        ${metricCard("Top-K", selectedStrategies.join(" / ") || "--")}
      </div>
      <div class="candidate-lanes">
        <div>
          <span>本地算法库得分</span>
          ${compactScoreList(localScores, 3)}
        </div>
        <div>
          <span>Agent 选择 Top-K</span>
          ${compactList(selectedStrategies.length ? selectedStrategies : ["等待运行结果"], 3)}
        </div>
        <div>
          <span>选择理由</span>
          ${compactReasonList(topkReasons, 3)}
        </div>
      </div>
      <details class="stage-detail">
        <summary>展开本地算法分数、策略来源和选择依据</summary>
        ${step.decision_reasoning ? `<p class="muted-line">${escapeHtml(step.decision_reasoning)}</p>` : ""}
        ${localScores.length ? `
        <div class="candidate-table">
          <table>
            <thead><tr><th>本地算法</th><th>状态</th><th>分数</th><th>耗时</th></tr></thead>
            <tbody>
              ${localScores.map((item) => `
                <tr>
                  <td><b>${escapeHtml(item.strategy)}</b></td>
                  <td>${escapeHtml(item.status || "--")}</td>
                  <td>${fmt(item.score)}</td>
                  <td>${fmt(item.runtime_ms, 1)}ms</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>` : ""}
        ${topkReasons.length ? `
        <div class="rule-list">
          ${topkReasons.map((item) => `<div><strong>${escapeHtml(item.strategy)}</strong><p>${escapeHtml(item.reason)}${item.score != null ? ` 基准分数 ${fmt(item.score)}。` : ""}</p></div>`).join("")}
        </div>` : ""}
        ${candidateCatalog.length ? `
        <div class="candidate-table">
          <table>
            <thead><tr><th>候选</th><th>来源</th><th>基于</th><th>参数</th></tr></thead>
            <tbody>
              ${candidateCatalog.map((item) => `
                <tr>
                  <td><b>${escapeHtml(item.name)}</b></td>
                  <td>${escapeHtml(formatSource(item.source || item.type))}</td>
                  <td>${escapeHtml(item.base_strategy || item.name)}</td>
                  <td><code>${escapeHtml(compactParams(item.parameters))}</code></td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>` : ""}
        <div class="rule-list">
          ${rules.map((item) => `<div><strong>${escapeHtml(item.rule)}</strong><p>${escapeHtml(item.reason)}</p></div>`).join("") || "<div><strong>static_pool</strong><p>使用稳定算法库默认策略池。</p></div>"}
        </div>
        <p class="muted-line">经验库命中：${memoryHits.length ? escapeHtml(memoryHits.map((item) => item.strategy || item).join(" / ")) : "没有新增经验库策略，使用规则策略池。"}</p>
      </details>
    `
  );
}

function renderScoreResult(result) {
  const scores = result.scoreboard || result.steps.find((step) => step.id === "score")?.scores || [];
  const range = scoreRange(scores);
  stageCard(
    "03",
    "算法评分榜",
    `完整展示初始策略池和在线调参阶段的分数，最终选择 ${result.online.selected_strategy}。`,
    `
      <div class="winner-strip">
        ${metricCard("最终算法", result.online.selected_strategy)}
        ${metricCard("最终分数", fmt(result.online.final_evaluation?.score))}
        ${metricCard("参与评分", fmt(scores.length, 0))}
      </div>
      <details class="stage-detail">
        <summary>展开完整评分榜</summary>
        <div class="score-table-wrap">
          <table class="score-table">
            <thead><tr><th>算法</th><th>来源</th><th>阶段</th><th>状态</th><th>分数</th><th>耗时</th><th>参数</th></tr></thead>
            <tbody>
            ${scores.map((item, index) => {
          const score = Number(item.score);
          const width = Number.isFinite(score) && Number.isFinite(range.min) && Number.isFinite(range.max) && range.max > range.min
            ? 100 - ((score - range.min) / (range.max - range.min) * 76)
            : 100;
          return `
            <tr class="${item.selected ? "selected" : index === 0 ? "best" : ""}">
              <td><b>${escapeHtml(item.strategy)}</b>${item.selected ? "<em>FINAL</em>" : item.initial_best ? "<em>INIT BEST</em>" : ""}</td>
              <td>${escapeHtml(formatSource(item.source))}${item.base_strategy && item.base_strategy !== item.strategy ? `<br><code>base=${escapeHtml(item.base_strategy)}</code>` : ""}</td>
              <td>${escapeHtml(item.phase || "--")}</td>
              <td>${escapeHtml(item.status || "--")}</td>
              <td><span class="score-line"><i style="--w:${Math.max(14, width)}%"></i></span><strong>${fmt(item.score)}</strong></td>
              <td>${fmt(item.runtime_ms, 1)}ms</td>
              <td><code>${escapeHtml(compactParams(item.parameters))}</code></td>
            </tr>
          `;
        }).join("")}
            </tbody>
          </table>
        </div>
      </details>
    `
  );
}

function compactScoreList(items, limit = 3) {
  const rows = (items || []).slice(0, limit);
  const hidden = Math.max(0, (items || []).length - rows.length);
  return `
    <div class="score-mini-list">
      ${rows.map((item) => `
        <div><b>${escapeHtml(item.strategy)}</b><span>${fmt(item.score)}</span></div>
      `).join("") || "<div><b>--</b><span>--</span></div>"}
      ${hidden ? `<div><b>more</b><span>+${hidden}</span></div>` : ""}
    </div>
  `;
}

function compactReasonList(items, limit = 3) {
  const rows = (items || []).slice(0, limit);
  const hidden = Math.max(0, (items || []).length - rows.length);
  return `
    <div class="reason-mini-list">
      ${rows.map((item) => `<p><b>${escapeHtml(item.strategy)}</b>${escapeHtml(item.reason)}</p>`).join("") || "<p>等待 Agent 决策。</p>"}
      ${hidden ? `<p><b>more</b>还有 ${hidden} 条理由。</p>` : ""}
    </div>
  `;
}

function compactParams(parameters) {
  const entries = Object.entries(parameters || {});
  if (!entries.length) return "--";
  return entries.map(([key, value]) => `${key}=${value}`).join(", ");
}

function renderDiagnostics(step) {
  const diagnostics = step.diagnostics || [];
  stageCard(
    "04",
    "分数诊断与调优方向",
    step.summary || "分析覆盖、成本和拒单风险，决定是否需要生成新候选。",
    `
      <div class="diagnostic-summary">
        ${diagnostics.slice(0, 3).map((item) => `<i class="${escapeHtml(item.severity || "info")}">${escapeHtml(item.code)}</i>`).join("")}
      </div>
      <details class="stage-detail">
        <summary>展开诊断详情</summary>
        <div class="diagnostic-list">
          ${diagnostics.length ? diagnostics.map((item) => `
            <div class="${escapeHtml(item.severity || "info")}">
              <b>${escapeHtml(item.code)}</b>
              <p>${escapeHtml(item.message)}</p>
            </div>
          `).join("") : "<div><b>no_major_issue</b><p>本轮没有主要异常诊断。</p></div>"}
        </div>
      </details>
    `
  );
}

function renderFinalSubmit(online) {
  const evaluation = online.final_evaluation || {};
  const summary = online.solution_summary || {};
  const code = online.final_submit?.code || online.selected_algorithm?.code || "";
  stageCard(
    "05",
    "保存 final_submit 并返回代码",
    `最终选择 ${online.selected_strategy}，分数 ${fmt(evaluation.score)}。`,
    `
      <div class="metric-grid compact">
        ${metricCard("覆盖订单", `${fmt(evaluation.covered_tasks, 0)}/${fmt((evaluation.covered_tasks || 0) + (evaluation.uncovered_tasks || 0), 0)}`)}
        ${metricCard("合单组", fmt(summary.pair_groups, 0))}
        ${metricCard("总分", fmt(evaluation.score))}
        ${metricCard("文件", fileName(online.final_submit?.path || "final_submit.py"))}
      </div>
      <details class="code-detail">
        <summary>展开完整最终算法代码</summary>
        <pre><code>${escapeHtml(code)}</code></pre>
      </details>
    `
  );
}

function scoreRows(items, limit = 5) {
  return `
    <div class="final-score-list">
      ${(items || []).slice(0, limit).map((item) => `
        <div>
          <b>${escapeHtml(item.strategy || item.name || "--")}</b>
          <span>${escapeHtml(item.phase ? formatSource(item.phase) : item.status || "")}</span>
          <strong>${fmt(item.score)}</strong>
        </div>
      `).join("") || "<div><b>--</b><span>暂无</span><strong>--</strong></div>"}
    </div>
  `;
}

function reasonRows(items, limit = 3) {
  return `
    <div class="final-reasons">
      ${(items || []).slice(0, limit).map((item) => `
        <p><b>${escapeHtml(item.strategy || "--")}</b>${escapeHtml(item.reason || item.value || "")}</p>
      `).join("") || "<p>无额外理由。</p>"}
    </div>
  `;
}

function agentDecisionText(decision) {
  if (!decision) return "{}";
  const body = decision.decision || {};
  const mode = body.decision_mode || "";
  const payload = {
    used_llm: decision.used_llm === true,
    status: decision.status || "unknown",
    model: decision.model || "LLM",
    fallback: decision.status !== "ok",
    fallback_type: mode === "recorded_agent_fallback" ? "recorded_closed_loop" : decision.status !== "ok" ? "rule_or_mock" : null,
    fallback_source: body.fallback_source || null,
    recorded_dataset: body.recorded_dataset || null,
    agent_output: body.agent_output || null,
    decision: body,
    error: compactLLMError(decision.error) || null,
    raw_text: decision.raw_text || ""
  };
  return JSON.stringify(payload, null, 2);
}

function compactAgentDecision(decision) {
  if (!decision) return null;
  const body = decision.decision || {};
  return {
    used_llm: decision.used_llm === true,
    status: decision.status || "unknown",
    model: decision.model || "LLM",
    fallback_type: body.decision_mode === "recorded_agent_fallback" ? "recorded_closed_loop" : decision.status !== "ok" ? "rule_or_mock" : null,
    fallback_source: body.fallback_source || null,
    recorded_dataset: body.recorded_dataset || null,
    agent_output: body.agent_output || null,
    decision: body,
    error: compactLLMError(decision.error) || null,
    raw_text: decision.raw_text || ""
  };
}

function combinedOnlineAgentDecision(topkDecision, tuningDecision) {
  if (!topkDecision && !tuningDecision) return null;
  const primary = topkDecision || tuningDecision || {};
  const topkBody = topkDecision?.decision || {};
  const tuningBody = tuningDecision?.decision || {};
  return {
    used_llm: topkDecision?.used_llm === true || tuningDecision?.used_llm === true,
    status: topkDecision?.status || tuningDecision?.status || "unknown",
    model: topkDecision?.model || tuningDecision?.model || "LLM",
    decision: {
      decision_mode: topkBody.decision_mode || tuningBody.decision_mode || "",
      fallback_source: topkBody.fallback_source || tuningBody.fallback_source || null,
      recorded_dataset: topkBody.recorded_dataset || tuningBody.recorded_dataset || null,
      online_agent_output: {
        stage_1_strategy_selection: compactAgentDecision(topkDecision),
        stage_2_score_diagnosis_and_tuning: compactAgentDecision(tuningDecision),
      },
    },
    raw_text: [topkDecision?.raw_text, tuningDecision?.raw_text].filter(Boolean).join("\n\n"),
    error: topkDecision?.error || tuningDecision?.error || primary.error || null,
  };
}

function analysisSummaryPanel(online) {
  const analysis = online.data_analysis || {};
  const metrics = analysis.metrics || {};
  const scene = analysis.scene || {};
  const features = (analysis.feature_table || []).slice(0, 5);
  return `
    <div class="final-analysis">
      <div>
        <span>数据分析结果</span>
        <b>${escapeHtml(scene.case_type || online.case_profile?.case_type || "--")}</b>
        <p>${escapeHtml(scene.summary || "已完成数据画像。")}</p>
      </div>
      <div class="analysis-pills">
        <i>合单 ${percent(metrics.pair_bundle_ratio)}</i>
        <i>意愿 ${fmt(metrics.willingness_mean, 3)}</i>
        <i>冲突 ${percent(metrics.conflict_density)}</i>
        <i>候选 ${fmt(metrics.candidates, 0)}</i>
      </div>
      <div class="analysis-feature-row">
        ${features.map((item) => `<em>${escapeHtml(item.name)}=${escapeHtml(formatFeatureValue(item))}</em>`).join("")}
      </div>
      <details class="analysis-detail">
        <summary>查看详细数据分析</summary>
        <div class="analysis-detail-grid">
          ${(analysis.feature_table || []).slice(0, 10).map((item) => `
            <div>
              <span>${escapeHtml(item.role || "feature")}</span>
              <b>${escapeHtml(item.name)}</b>
              <strong>${escapeHtml(formatFeatureValue(item))}</strong>
            </div>
          `).join("")}
        </div>
        <div class="scene-rule-grid compact-rule-grid">
          ${(scene.rules || online.case_profile?.case_label_rules || []).map((rule) => `
            <div class="${rule.matched ? "matched" : ""}">
              <strong>${escapeHtml(rule.label)}</strong>
              <em>${rule.matched ? "MATCHED" : "NO"}</em>
              <span>${escapeHtml(rule.metric)}=${escapeHtml(formatFeatureValue({ name: rule.metric, value: rule.value }))}</span>
              <p>${escapeHtml(rule.reason || (rule.matched ? "命中该场景。" : "未触发。"))}</p>
            </div>
          `).join("")}
        </div>
      </details>
    </div>
  `;
}

function agentOutputPanel(title, decision) {
  const mode = decision?.decision?.decision_mode;
  const badge = mode === "recorded_agent_fallback" || decision?.status === "recorded_fallback"
    ? "录制闭环 fallback"
    : decision?.used_llm && decision?.status === "ok"
      ? "LLM live"
      : "fallback";
  return `
    <details class="agent-final-output" open>
      <summary><span>${escapeHtml(title)} 输出结果</span><b>${escapeHtml(badge)}</b></summary>
      <pre><code>${escapeHtml(agentDecisionText(decision))}</code></pre>
    </details>
  `;
}

function offlineIterationTimeline(rounds) {
  const items = (rounds || []).slice(0, 4);
  if (!items.length) return "";
  return `
    <section class="offline-iteration-panel">
      <div class="iteration-title">
        <span>离线 Agent 自主迭代轨迹</span>
        <b>${fmt(items.length, 0)} 轮</b>
      </div>
      <div class="iteration-rounds">
        ${items.map((item) => `
          <div>
            <i>R${escapeHtml(item.round)}</i>
            <strong>${escapeHtml(item.title || "--")}</strong>
            <p>${escapeHtml(item.agent_action || "")}</p>
            <em>${escapeHtml(item.result || "")}</em>
            <small>${escapeHtml((item.writes || []).join(" / "))}</small>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function learnedWritesPanel(writes) {
  const rows = (writes || []).slice(0, 10);
  if (!rows.length) return "";
  return `
    <section class="learned-write-panel">
      <div class="iteration-title">
        <span>已写入 demo 经验库</span>
        <b>离线 Agent 自主迭代得到</b>
      </div>
      <div class="learned-write-grid">
        ${rows.map((item) => `
          <div>
            <span>${escapeHtml(item.label || item.type || "经验")}</span>
            <b>${escapeHtml(item.name || "--")}</b>
            <p>${escapeHtml(item.content || "")}</p>
            <em>${escapeHtml(item.source || "离线 Agent 自主迭代得到")}</em>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function offlineAssetPoolPanel(showcase) {
  const algorithms = showcase.new_algorithms || [];
  const scenes = showcase.new_scenes || (showcase.new_scene ? [showcase.new_scene] : []);
  const writes = showcase.learned_writes || [];
  const policyWrites = writes.filter((item) => item.type === "policy");
  return `
    <section class="asset-pool-panel">
      <div class="iteration-title">
        <span>离线沉淀资产池</span>
        <b>证明系统可持续进化</b>
      </div>
      <div class="asset-pool-grid">
        <div>
          <span>算法库新增</span>
          <strong>${fmt(algorithms.length, 0)} 个</strong>
          ${compactList(algorithms.map((item) => item.name), 5)}
        </div>
        <div>
          <span>场景池新增</span>
          <strong>${fmt(scenes.length, 0)} 类</strong>
          ${compactList(scenes.map((item) => item.id), 4)}
        </div>
        <div>
          <span>策略规则新增</span>
          <strong>${fmt(policyWrites.length, 0)} 条</strong>
          ${compactList(policyWrites.map((item) => item.name), 4)}
        </div>
      </div>
    </section>
  `;
}

function onlineAgentOutputPanel(topkDecision, tuningDecision) {
  const combined = combinedOnlineAgentDecision(topkDecision, tuningDecision);
  const mode = combined?.decision?.decision_mode;
  const badge = mode === "recorded_agent_fallback" || combined?.status === "recorded_fallback"
    ? "录制闭环 fallback"
    : combined?.used_llm && combined?.status === "ok"
      ? "LLM live"
      : "fallback";
  return `
    <details class="agent-final-output online-agent-output" open>
      <summary><span>在线 Agent 决策输出</span><b>${escapeHtml(badge)}</b></summary>
      <div class="online-agent-brief">
        <div>
          <span>策略初选</span>
          <p>基于数据分析和本地算法库基准分数，选择本轮继续运行的 Top-K 策略。</p>
        </div>
        <div>
          <span>结果诊断 / 调参</span>
          <p>基于 Top-K 跑分和诊断结果，决定是否在时间预算内尝试参数候选。</p>
        </div>
      </div>
      <pre><code>${escapeHtml(agentDecisionText(combined))}</code></pre>
    </details>
  `;
}

function renderOnlineFinalDashboard(result) {
  const online = result.online || {};
  const evaluation = online.final_evaluation || {};
  const profile = online.case_profile || {};
  const metrics = online.data_analysis?.metrics || {};
  const planStep = result.steps.find((step) => step.id === "plan") || {};
  const diagnoseStep = result.steps.find((step) => step.id === "diagnose") || {};
  const scores = result.scoreboard || [];
  const localScores = planStep.local_scores || [];
  const topk = planStep.selected_strategies || [];
  const decision = online.online_agent?.topk_decision || {};
  const tuningDecision = online.online_agent?.tuning_decision || {};
  const code = online.final_submit?.code || online.selected_algorithm?.code || "";
  byId("stage-results").innerHTML = `
    <article class="final-dashboard">
      <section class="final-hero">
        <div>
          <span>ONLINE RESULT</span>
          <h3>${escapeHtml(online.selected_strategy || "--")}</h3>
          <p>${escapeHtml(llmLabel(decision))} · final_submit.py 已生成</p>
        </div>
        <strong>${fmt(evaluation.score)}</strong>
      </section>

      <section class="final-kpis">
        ${metricCard("场景", profile.case_type || "--")}
        ${metricCard("订单/骑手", `${fmt(metrics.orders || profile.num_tasks, 0)}/${fmt(metrics.couriers || profile.num_couriers, 0)}`)}
        ${metricCard("候选关系", fmt(metrics.candidates || profile.num_candidates, 0))}
        ${metricCard("覆盖", `${fmt(evaluation.covered_tasks, 0)}/${fmt((evaluation.covered_tasks || 0) + (evaluation.uncovered_tasks || 0), 0)}`)}
        ${metricCard("参与评分", fmt(scores.length, 0))}
      </section>

      ${analysisSummaryPanel(online)}

      <section class="final-panels">
        <div class="final-panel">
          <span>本地算法库基准 Top</span>
          ${scoreRows(localScores, 4)}
        </div>
        <div class="final-panel">
          <span>Agent Top-K</span>
          ${compactList(topk, 5)}
          ${reasonRows(planStep.topk_reasons || [], 2)}
        </div>
        <div class="final-panel">
          <span>最终评分榜</span>
          ${scoreRows(scores, 5)}
        </div>
        <div class="final-panel">
          <span>诊断结论</span>
          <div class="final-diagnostics">
            ${(diagnoseStep.diagnostics || []).slice(0, 3).map((item) => `<i>${escapeHtml(item.code)}</i>`).join("") || "<i>no_major_issue</i>"}
          </div>
          <p>${escapeHtml((diagnoseStep.diagnostics || [])[0]?.message || "当前结果没有主要异常。")}</p>
        </div>
      </section>

      <section class="agent-output-grid">
        ${onlineAgentOutputPanel(decision, tuningDecision)}
      </section>

      <details class="code-detail final-code">
        <summary>展开 final_submit.py 代码</summary>
        <pre><code>${escapeHtml(code)}</code></pre>
      </details>
    </article>
  `;
}

function renderOfflineFinalDashboard(result, step) {
  const showcase = step.showcase || result.offline_showcase || {};
  const newAlgorithms = showcase.new_algorithms || [];
  const newScene = showcase.new_scene || {};
  const newScenes = showcase.new_scenes || (newScene.id ? [newScene] : []);
  const nextOnline = showcase.next_online_usage || {};
  const iterationRounds = showcase.iteration_rounds || [];
  const learnedWrites = showcase.learned_writes || [];
  const ablation = (step.ablation_summary || [])[0]?.result || {};
  const bestTrial = ablation.best_trial || {};
  const details = result.memory_details || [];
  const offlineDecision = firstOfflineDecision(result) || showcase.memory_entry?.offline_agent?.ablation_decision || {};
  const online = result.online || {};
  byId("stage-results").innerHTML = `
    <article class="final-dashboard offline-final">
      <section class="final-hero">
        <div>
          <span>OFFLINE RESULT</span>
          <h3>${escapeHtml(newAlgorithms[0]?.name || "经验库已更新")}</h3>
          <p>离线 Agent 自主迭代得到新算法、场景规则和策略选择经验</p>
        </div>
        <strong>${escapeHtml(bestTrial.score ? fmt(bestTrial.score) : fmt(ablation.baseline_score))}</strong>
      </section>

      <section class="final-kpis">
        ${metricCard("自主迭代", `${fmt(iterationRounds.length || step.stop_policy?.max_iterations || result.offline_config?.max_iterations, 0)} 轮`)}
        ${metricCard("新策略", fmt(newAlgorithms.length, 0))}
        ${metricCard("新场景", `${fmt(newScenes.length, 0)} 类`)}
        ${metricCard("提升", percent(bestTrial.relative_improvement || 0, 2))}
        ${metricCard("写入项", fmt(learnedWrites.length || (details[0]?.experience || []).length, 0))}
      </section>

      ${analysisSummaryPanel(online)}

      ${offlineIterationTimeline(iterationRounds)}

      ${offlineAssetPoolPanel(showcase)}

      <section class="final-panels">
        <div class="final-panel">
          <span>新增算法代码 · 离线 Agent 自主迭代得到</span>
          ${compactList(newAlgorithms.map((item) => item.name), 3)}
          <p>${escapeHtml(newAlgorithms[0]?.description || "--")}</p>
        </div>
        <div class="final-panel">
          <span>新增场景分类 · 离线 Agent 自主迭代得到</span>
          <b>${escapeHtml(newScenes.map((item) => item.id).join(" / ") || "--")}</b>
          <p>${escapeHtml(newScenes.map((item) => item.condition).filter(Boolean).join("；") || "--")}</p>
        </div>
        <div class="final-panel">
          <span>消融试验结果</span>
          ${scoreRows((ablation.trials || []).map((item) => ({ ...item, phase: "offline_generated" })), 3)}
        </div>
        <div class="final-panel">
          <span>下次在线如何引用</span>
          ${compactList(nextOnline.topk_injection || [], 3)}
          <p>${escapeHtml(nextOnline.reason || "经验库会作为下一次 Top-K 决策依据。")}</p>
        </div>
      </section>

      ${learnedWritesPanel(learnedWrites)}

      <section class="agent-output-grid">
        ${agentOutputPanel("离线消融 Agent", offlineDecision)}
      </section>

      <details class="stage-detail final-detail">
        <summary>展开写入经验库内容</summary>
        <div class="memory-list">
          ${details.slice(0, 2).map((item) => `
            <div>
              <span>${escapeHtml(item.case_type)}</span>
              <b>${escapeHtml((item.preferred_strategies || []).join(" / ") || "--")}</b>
              ${(item.experience || []).map((exp) => `<p><strong>${escapeHtml(exp.label)}：</strong>${escapeHtml(exp.value)}</p>`).join("")}
            </div>
          `).join("")}
        </div>
      </details>
    </article>
  `;
}

function renderOfflineMemory(result, step) {
  const memory = step.memory || {};
  const learned = step.learned_code || {};
  const details = result.memory_details || [];
  const offlineDecision = firstOfflineDecision(result);
  const demoState = result.demo_state || {};
  const policy = step.stop_policy || result.offline_config || {};
  const source = step.evidence_source || result.evidence_source;
  const sourceLabel = source === "offline_bootstrap" ? "离线自建基准日志" : "复用当前 demo 日志";
  const ablations = step.ablation_summary || [];
  const showcase = step.showcase || result.offline_showcase || {};
  const newAlgorithms = showcase.new_algorithms || [];
  const newScene = showcase.new_scene || null;
  const nextOnline = showcase.next_online_usage || {};
  stageCard(
    "06",
    "离线 Agent 写入经验库",
    step.summary || "离线阶段建立实验证据，做消融探索，并把规律写入 demo 经验库。",
    `
      <div class="metric-grid compact">
        ${metricCard("证据来源", sourceLabel)}
        ${metricCard("场景数", fmt(step.metrics?.case_types, 0))}
        ${metricCard("新策略模块", fmt(step.metrics?.generated_modules, 0))}
        ${metricCard("最大迭代", `${fmt(policy.max_iterations, 0)} 轮`)}
      </div>
      <div class="iteration-note">
        最大迭代轮数限制离线消融 trial 的数量。设置为 ${escapeHtml(fmt(policy.max_iterations, 0))}，本轮最多试跑 ${escapeHtml(fmt(policy.max_iterations, 0))} 个候选参数/算法变体。
      </div>
      ${showcase.enabled ? `
      <div class="offline-showcase">
        <div>
          <span>新策略代码</span>
          <b>${escapeHtml(newAlgorithms.map((item) => item.name).join(" / ") || "--")}</b>
          <p>${escapeHtml(newAlgorithms[0]?.description || "离线 Agent 本轮没有模拟新策略。")}</p>
        </div>
        <div>
          <span>新场景分类</span>
          <b>${escapeHtml(newScene?.id || "--")}</b>
          <p>${escapeHtml(newScene?.condition || "--")}</p>
        </div>
        <div>
          <span>下次在线引用</span>
          <b>${escapeHtml((nextOnline.topk_injection || []).join(" / ") || "--")}</b>
          <p>${escapeHtml(nextOnline.reason || "经验库会作为下一次 Top-K 决策依据。")}</p>
        </div>
      </div>` : ""}
      <div class="memory-write">
        <b>写入内容预览</b>
        <p>${escapeHtml(showcase.enabled ? "录制 Offline Agent fallback 已展示消融分析和经验写入" : llmLabel(offlineDecision))}。本次写入 demo 沙箱，不污染正式经验库。</p>
        <code>${escapeHtml(shortPath(demoState.memory_path || ""))}</code>
        <div class="tag-list">
          ${details.flatMap((item) => item.valuable_features || []).slice(0, 8).map((feature) => `<i>${escapeHtml(feature.name || feature)}</i>`).join("") || "<i>暂无新增特征</i>"}
        </div>
      </div>
      <details class="stage-detail">
        <summary>展开离线一轮完整输出</summary>
        ${renderAblationSummary(ablations)}
      </details>
      <details class="stage-detail">
        <summary>展开经验库内容</summary>
        <div class="memory-list">
          ${details.map((item) => `
            <div>
              <span>${escapeHtml(item.case_type)}</span>
              <b>${escapeHtml((item.preferred_strategies || []).join(" / ") || item.best_strategy || "--")}</b>
              ${(item.experience || []).map((exp) => `<p><strong>${escapeHtml(exp.label)}：</strong>${escapeHtml(exp.value)}</p>`).join("")}
            </div>
          `).join("") || "<div><span>memory</span><b>暂无可展示经验</b><p>先积累更多离线实验证据。</p></div>"}
        </div>
        <p class="muted-line">本轮新增模块：${Object.keys(learned).length ? escapeHtml(Object.keys(learned).join(" / ")) : "没有更优消融结果，因此没有强制新增算法。"}</p>
        ${showcase.enabled ? `<p class="muted-line">Demo 模拟新增：${escapeHtml(newAlgorithms.map((item) => item.name).join(" / "))}；新场景：${escapeHtml(newScene?.id || "--")}。</p>` : ""}
      </details>
    `
  );
}

function renderAblationSummary(items) {
  if (!items.length) {
    return `<div class="empty-state">暂无消融输出。离线阶段需要至少一份可分析的实验日志。</div>`;
  }
  return `
    <div class="ablation-list">
      ${items.map((item) => {
        const decision = item.decision || {};
        const result = item.result || {};
        const trials = result.trials || [];
        const planned = decision.decision?.ablation_trials || [];
        return `
          <article>
            <h4>${escapeHtml(item.case_type)}</h4>
            <p>LLM/规则计划：${escapeHtml(decision.status || "unknown")}，候选 ${fmt(planned.length, 0)} 个；实际试跑 ${fmt(trials.length, 0)} 个；停止原因 ${escapeHtml(result.stop_reason || "--")}。</p>
            <div class="trial-table">
              <table>
                <thead><tr><th>轮次</th><th>候选</th><th>分数</th><th>相对提升</th><th>状态</th><th>参数</th></tr></thead>
                <tbody>
                  ${trials.map((trial, index) => `
                    <tr>
                      <td>${index + 1}</td>
                      <td><b>${escapeHtml(trial.strategy)}</b></td>
                      <td>${fmt(trial.score)}</td>
                      <td>${percent(trial.relative_improvement || 0, 2)}</td>
                      <td>${escapeHtml(trial.status || "--")}</td>
                      <td><code>${escapeHtml(compactParams(trial.parameters))}</code></td>
                    </tr>
                  `).join("") || `<tr><td colspan="6">没有可执行 trial。</td></tr>`}
                </tbody>
              </table>
            </div>
            <p>写入结果：${item.promoted ? "发现更优结果，写入候选算法库/经验库。" : "没有达到可复用提升，本轮只写入分析经验。"}</p>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function updateDatasetSummary(snapshot) {
  const metrics = snapshot.analysis?.metrics || {};
  byId("dataset-summary").innerHTML = `
    <div><span>订单数</span><b>${escapeHtml(fmt(metrics.orders, 0))}</b></div>
    <div><span>骑手数</span><b>${escapeHtml(fmt(metrics.couriers, 0))}</b></div>
    <div><span>数据行数</span><b>${escapeHtml(fmt(metrics.candidates, 0))}</b></div>
  `;
  byId("case-type").textContent = "--";
  byId("case-summary").textContent = "点击运行后生成 Case Profile。";
}

function updateCaseProfileFromOnline(online) {
  const caseType = online?.data_analysis?.scene?.case_type || online?.case_profile?.case_type || "--";
  const summary = online?.data_analysis?.scene?.summary || "已完成数据画像。";
  byId("case-type").textContent = caseType;
  byId("case-summary").textContent = summary;
}

function updateModeControls() {
  const mode = getRunMode();
  byId("online-budget-row").hidden = mode !== "online";
  byId("offline-budget-row").hidden = mode !== "offline";
  byId("budget-note").textContent = mode === "online"
    ? "在线 Agent 在预算内选择 Top-K 策略、并行评分、调参迭代，返回当前最优代码。"
    : "离线 Agent 最多执行指定轮数的消融 trial，逐轮记录参数、分数和经验写入结果。";
  byId("start-run-button").textContent = mode === "online" ? "开始在线运行" : "开始离线运行";
}

function updateRunSummary(result) {
  const selected = result.online?.selected_strategy || "--";
  const score = result.online?.final_evaluation?.score;
  const evaluation = result.online?.final_evaluation || {};
  byId("best-strategy").textContent = selected;
  byId("best-strategy-meta").textContent = `final_submit 已生成，覆盖 ${fmt(evaluation.covered_tasks, 0)} 个订单。`;
  byId("best-score").textContent = fmt(score);
  byId("best-score-meta").textContent = `${llmLabel(result.online?.online_agent?.topk_decision || {})}`;
  byId("final-summary-strategy").textContent = selected;
  byId("final-summary-score").textContent = fmt(score);
  updateCaseProfileFromOnline(result.online);
}

function resetDashboard() {
  state.demo = null;
  state.onlineResult = null;
  setTraceTotal(9);
  setStatus("", "READY");
  resetResults();
  byId("stage-results").innerHTML = `<div class="empty-state tall">在线闭环负责快速返回当前最优代码；离线闭环可独立运行，负责实验复盘和经验库更新。</div>`;
  byId("timeline").innerHTML = `<div class="trace-empty">在线和离线是两个入口：在线求当前最优解，离线做实验和经验沉淀。</div>`;
  byId("trace-count").textContent = `0/${state.traceTotal}`;
  byId("best-strategy").textContent = "--";
  byId("best-strategy-meta").textContent = "在线 Agent 完成后生成。";
  byId("best-score").textContent = "--";
  byId("best-score-meta").textContent = "分数越低越好。";
  byId("case-type").textContent = "--";
  byId("case-summary").textContent = "点击运行后生成 Case Profile。";
  byId("final-summary-strategy").textContent = "--";
  byId("final-summary-score").textContent = "--";
}

async function previewDataset() {
  const payload = await getJSON("/api/datasets/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset: getDatasetPayload() })
  });
  state.snapshot = payload.result;
  renderKnowledge(state.snapshot);
  updateDatasetHeader();
  updateDatasetSummary(state.snapshot);
  resetDashboard();
}

async function handleDatasetUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const message = byId("dataset-message");
  message.textContent = `正在读取 ${file.name}。`;
  try {
    const text = await file.text();
    if (!text.trim()) throw new Error("文件为空");
    state.dataset = {
      name: file.name,
      source: "uploaded",
      inputText: text
    };
    state.demo = null;
    state.onlineResult = null;
    await previewDataset();
    message.textContent = `已加载 ${file.name}，在线和离线入口都会使用该数据集。`;
  } catch (error) {
    message.textContent = `上传失败：${error.message}`;
  }
}

async function useDefaultDataset() {
  state.dataset = {
    name: "large_seed301.txt",
    source: "default",
    inputText: ""
  };
  state.demo = null;
  state.onlineResult = null;
  state.snapshot = state.defaultSnapshot;
  renderKnowledge(state.snapshot);
  updateDatasetHeader();
  updateDatasetSummary(state.snapshot);
  resetDashboard();
  byId("dataset-message").textContent = "已切回默认 large_seed301。";
  const input = byId("dataset-file");
  if (input) input.value = "";
}

async function testLLMConnection() {
  relaxBaseURLInputValidation();
  const config = getLLMConfig();
  const button = byId("llm-test-button");
  button.disabled = true;
  setLLMStatus("testing", "测试中", "正在请求 DeepSeek 兼容接口。");
  try {
    const payload = await getJSON("/api/llm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ llm: config })
    });
    state.llmTest = payload.result;
    if (payload.result.ok) {
      setLLMStatus("ok", "可用", `${payload.result.model} 连接成功。`);
    } else {
      setLLMStatus("failed", "调用失败", payload.result.error || `${payload.result.model} 未返回有效 JSON。`);
    }
  } catch (error) {
    state.llmTest = null;
    setLLMStatus("failed", "调用失败", error.message);
  } finally {
    button.disabled = false;
  }
}

function setRunButtonsDisabled(disabled) {
  ["start-run-button"].forEach((id) => {
    const button = byId(id);
    if (button) button.disabled = disabled;
  });
  const interrupt = byId("interrupt-button");
  if (interrupt) interrupt.disabled = !disabled;
}

function beginRun() {
  if (state.abortController) {
    state.abortController.abort();
  }
  state.abortController = new AbortController();
  setRunButtonsDisabled(true);
  return state.abortController.signal;
}

function endRun(signal) {
  if (state.abortController?.signal === signal) {
    state.abortController = null;
  }
  setRunButtonsDisabled(false);
}

function renderOnlineResult(result) {
  renderKnowledge(result);
  updateRunSummary(result);
  renderOnlineFinalDashboard(result);
}

async function requestOnlineDemo() {
  const signal = state.abortController?.signal;
  const payload = await getJSON("/api/autosolver/online-demo", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      time_budget: Number(byId("time-budget")?.value || 10),
      seed: 301,
      dataset: getDatasetPayload(),
      llm: getLLMConfig()
    })
  });
  return payload.result;
}

async function requestOfflineDemo(baseResult) {
  const signal = state.abortController?.signal;
  const payload = await getJSON("/api/autosolver/offline-demo", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      time_budget: Number(byId("time-budget")?.value || 10),
      seed: 301,
      dataset: getDatasetPayload(),
      llm: getLLMConfig(),
      offline: getOfflineConfig()
    })
  });
  return payload.result;
}

async function runOnlineDemo(keepExisting = false, traceOffset = 0, traceTotal = 7) {
  relaxBaseURLInputValidation();
  const signal = beginRun();
  setTraceTotal(traceTotal);
  setStatus("running", "RUNNING");
  if (!keepExisting) {
    resetResults();
    resetTrace();
  }
  try {
    if (!keepExisting) byId("timeline").innerHTML = "";
    await appendTrace("run", "载入数据", `读取 ${state.dataset.name || "large_seed301.txt"}，解析订单、骑手和候选关系。`, traceOffset + 1);
    await appendTrace("run", "数据分析 + 本地基准", "计算数据画像，同步运行本地算法库得到第一批基准分数。", traceOffset + 2);
    await appendTrace("run", "Agent 选择 Top-K", "把数据画像和本地算法分数送入 LLM；无 Key 或超时时展示录制闭环 fallback。", traceOffset + 3);
    const result = await requestOnlineDemo();
    state.demo = result;
    state.onlineResult = result;
    renderOnlineResult(result);
    const planStep = result.steps.find((step) => step.id === "plan") || {};
    await appendTrace("score", "Top-K 决策完成", `${planStep.decision_mode === "llm" ? "LLM" : planStep.decision_mode === "recorded_agent_fallback" ? "录制闭环 fallback" : "Mock Agent"} 选择 ${((planStep.selected_strategies || []).join(" / ")) || "--"}。`, traceOffset + 4);
    await appendTrace("score", "并行策略评分完成", `最优策略 ${result.online.selected_strategy}，分数 ${fmt(result.online.final_evaluation?.score)}。`, traceOffset + 5);
    await appendTrace("diagnose", "分数诊断", "分析当前分数结构，判断是否需要参数调优或生成新候选。", traceOffset + 6);
    await appendTrace("done", "生成 final_submit", fileName(result.online.final_submit?.path || "final_submit.py"), traceOffset + 7);
    setStatus("done", "DONE");
    return result;
  } catch (error) {
    if (error.name === "AbortError") {
      await appendTrace("failed", "运行已中断", "当前请求已取消。", byId("timeline").querySelectorAll(".trace-step").length + 1);
      setStatus("failed", "INTERRUPTED");
      return null;
    }
    const timeline = byId("timeline");
    const nextIndex = timeline ? Math.max(1, timeline.querySelectorAll(".trace-step").length + 1) : 1;
    if (timeline) {
      await appendTrace("failed", "运行失败", error.message, nextIndex);
    }
    stageCard("ERR", "运行失败", error.message, "");
    setStatus("failed", "FAILED");
    throw error;
  } finally {
    endRun(signal);
  }
}

async function runOfflineDemo(traceOffset = 0, traceTotal = null) {
  relaxBaseURLInputValidation();
  const signal = beginRun();
  setTraceTotal(traceTotal || 4);
  setStatus("running", "RUNNING");
  try {
    resetResults();
    byId("timeline").innerHTML = "";
    await appendTrace(
      "learn",
      "建立离线基准日志",
      "离线 Agent 独立运行基准策略，先生成可分析的实验证据。",
      traceOffset + 1
    );
    await appendTrace("learn", "离线消融实验", `最多执行 ${fmt(getOfflineConfig().max_iterations, 0)} 轮消融 trial，逐轮记录参数、分数和经验写入结果。`, traceOffset + 2);
    const result = await requestOfflineDemo();
    state.demo = result;
    state.onlineResult = result;
    renderKnowledge(result);
    const memoryStep = result.steps.find((step) => step.id === "memory") || {};
    renderOfflineFinalDashboard(result, memoryStep);
    const showcaseLabel = memoryStep.showcase?.enabled ? "录制 Offline Agent fallback 发现 pair-rich 低意愿规律，并生成新策略。" : llmLabel(firstOfflineDecision(result));
    await appendTrace("learn", "分析可复用规律", showcaseLabel, traceOffset + 3);
    await appendTrace("learn", "写入 demo 经验库", "展示离线阶段沉淀的特征、场景和策略偏好。", traceOffset + 4);
    setStatus("done", "DONE");
  } catch (error) {
    if (error.name === "AbortError") {
      await appendTrace("failed", "运行已中断", "当前请求已取消。", byId("timeline").querySelectorAll(".trace-step").length + 1);
      setStatus("failed", "INTERRUPTED");
      return;
    }
    const timeline = byId("timeline");
    const nextIndex = timeline ? Math.max(1, timeline.querySelectorAll(".trace-step").length + 1) : 1;
    if (timeline) {
      await appendTrace("failed", "运行失败", error.message, nextIndex);
    }
    stageCard("ERR", "运行失败", error.message, "");
    setStatus("failed", "FAILED");
  } finally {
    endRun(signal);
  }
}

function startSelectedRun() {
  if (getRunMode() === "online") {
    runOnlineDemo(false).catch(() => {});
  } else {
    runOfflineDemo();
  }
}

async function initialize() {
  relaxBaseURLInputValidation();
  const payload = await getJSON("/api/datasets/largeseed301");
  state.snapshot = payload.result;
  state.defaultSnapshot = payload.result;
  renderKnowledge(state.snapshot);
  updateDatasetHeader();
  updateDatasetSummary(state.snapshot);
  updateModeControls();
}

byId("start-run-button").addEventListener("click", startSelectedRun);
byId("reset-button").addEventListener("click", resetDashboard);
byId("interrupt-button").addEventListener("click", () => {
  if (state.abortController) {
    state.abortController.abort();
  } else {
    setStatus("failed", "INTERRUPTED");
  }
});
byId("llm-test-button").addEventListener("click", testLLMConnection);
byId("dataset-file").addEventListener("change", handleDatasetUpload);
byId("default-dataset-button").addEventListener("click", () => useDefaultDataset().catch((error) => {
  byId("dataset-message").textContent = `切换失败：${error.message}`;
}));
document.querySelectorAll("input[name='run-mode']").forEach((input) => {
  input.addEventListener("change", updateModeControls);
});

initialize().catch((error) => {
  byId("stage-results").innerHTML = `<div class="empty-state tall">初始化失败：${escapeHtml(error.message)}</div>`;
  setStatus("failed", "FAILED");
});
