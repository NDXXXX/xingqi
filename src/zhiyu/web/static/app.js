await window.zhiyuDialogsReady;

const state = { conversationId: null, busy: false };
const views = ["overview", "chat", "providers", "channels", "mcp", "skills", "diagnostics", "memory"];

const $ = (selector) => document.querySelector(selector);
const messages = $("#messages");
const activity = $("#activity");
const input = $("#message-input");
const send = $("#send");
const dialogs = window.zhiyuDialogs;

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function clearEmpty() {
  messages.querySelector(".empty-state")?.remove();
}

function addMessage(role, content = "") {
  clearEmpty();
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.innerHTML = `<span class="role">${role === "user" ? "你" : "知语"}</span><span class="content"></span>`;
  node.querySelector(".content").textContent = content;
  messages.append(node);
  node.scrollIntoView({ behavior: "smooth", block: "end" });
  return node.querySelector(".content");
}

async function json(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function loadRuntime() {
  const urls = ["/api/health", "/api/providers", "/api/providers/default", "/api/channels", "/api/channel-events?limit=50", "/api/mcp/servers", "/api/skills", "/api/qq/config"];
  const results = await Promise.allSettled(urls.map((url) => json(url)));
  const [healthResult, providersResult, defaultResult, channelsResult, eventsResult, mcpResult, skillsResult, qqConfigResult] = results;
  const unavailable = (result) => result.status === "rejected";
  if (unavailable(healthResult)) {
    $("#health-dot").classList.remove("ok");
    $("#health-text").textContent = "状态读取失败";
    $("#runtime-detail").textContent = healthResult.reason.message;
    $("#overview-status").textContent = "无法读取状态";
    $("#overview-status").className = "status-pill warn";
    $("#system-runtime").textContent = "读取失败";
    return;
  }

  const health = healthResult.value;
  const providers = providersResult.status === "fulfilled" ? providersResult.value : null;
  const channels = channelsResult.status === "fulfilled" ? channelsResult.value : [];
  const events = eventsResult.status === "fulfilled" ? eventsResult.value : [];
  const mcpServers = mcpResult.status === "fulfilled" ? mcpResult.value : null;
  const skills = skillsResult.status === "fulfilled" ? skillsResult.value : null;
  const qq = channels.find((item) => item.channel === "qq");
  const failed = events.filter((item) => item.status === "failed").length;
  const pending = events.filter((item) => ["pending", "processing", "responded"].includes(item.status)).length;
  const enabledProviders = providers?.filter((item) => item.enabled && item.configured) ?? [];
  const enabledMcp = mcpServers?.filter((item) => item.enabled) ?? [];
  const mcpReady = enabledMcp.filter((item) => item.status === "ready").length;
  const skillCount = skills?.filter((item) => item.enabled && item.available).length ?? 0;
  const enabledSkills = skills?.filter((item) => item.enabled).length ?? 0;
  const selectedModel = defaultResult.status === "fulfilled" ? defaultResult.value : null;
  const firstProvider = enabledProviders[0];
  const modelText = selectedModel?.model
    ? `${selectedModel.provider} · ${selectedModel.model}`
    : defaultResult.status === "fulfilled"
      ? "未配置"
      : firstProvider
        ? `${firstProvider.name} · ${firstProvider.models[0] || "可用"}（默认模型接口不可用）`
        : "模型状态接口不可用";
  const runtimeProblems = [];
  if (!health.started) runtimeProblems.push("运行时未启动");
  if (health.degraded) runtimeProblems.push("渠道启动异常");
  if (qq && qq.status !== "connected") runtimeProblems.push("QQ 未连接");
  if (enabledMcp.some((item) => item.status !== "ready")) runtimeProblems.push("MCP 异常");
  if (skills?.some((item) => item.enabled && !item.available)) runtimeProblems.push("Skill 缺少依赖");
  if (!enabledProviders.length) runtimeProblems.push("未配置可用模型");
  if (!providers) runtimeProblems.push("模型状态接口不可用");
  if (failed) runtimeProblems.push(`${failed} 条失败事件`);
  const optionalApiProblems = [mcpResult, skillsResult].filter(unavailable).length;
  if (optionalApiProblems) runtimeProblems.push("扩展状态接口不可用");
  const overallStatus = runtimeProblems.length ? "需要检查" : "运行正常";
  $("#health-dot").classList.toggle("ok", health.started && !runtimeProblems.length);
  $("#health-text").textContent = health.started ? overallStatus : "服务未启动";
  $("#overview-status").textContent = overallStatus;
  $("#overview-status").className = `status-pill ${runtimeProblems.length ? "warn" : "good"}`;
  $("#runtime-detail").textContent = [
    qq ? `QQ ${qq.status}` : "QQ 状态未知",
    mcpServers ? (mcpServers.length ? `MCP ${enabledMcp.length ? `${mcpReady}/${enabledMcp.length} 正常` : `${mcpServers.length} 已配置 · 0 启用`}` : "MCP 未配置") : "MCP 状态接口不可用",
    skills ? (skills.length ? `Skills ${enabledSkills ? `${skillCount}/${enabledSkills} 可用` : `${skills.length} 已配置 · 0 启用`}` : "Skills 未配置") : "Skills 状态接口不可用",
    `待处理 ${pending} · 失败 ${failed}`,
  ].join(" · ");
  $("#model-badge").textContent = modelText;
  $("#stat-qq").textContent = qq ? (qq.status === "connected" ? "已连接" : qq.status) : "未知";
  $("#stat-provider").textContent = providers ? enabledProviders.length : "不可用";
  $("#stat-mcp").textContent = !mcpServers ? "不可用" : !mcpServers.length ? "未配置" : !enabledMcp.length ? `${mcpServers.length} 已配置` : `${mcpReady} / ${enabledMcp.length}`;
  $("#stat-skills").textContent = !skills ? "不可用" : !skills.length ? "未配置" : !enabledSkills ? `${skills.length} 已配置` : `${skillCount} / ${enabledSkills}`;
  $("#stat-pending").textContent = eventsResult.status === "fulfilled" ? pending : "不可用";
  $("#system-runtime").textContent = health.started ? (health.degraded ? "部分降级" : "运行中") : "未启动";
  $("#system-model").textContent = modelText;
  $("#system-owner").textContent = qqConfigResult.status === "fulfilled" ? (qqConfigResult.value?.owner_user_id || "未设置") : "接口不可用";

  const healthRows = [
    { name: "知语运行时", detail: health.started ? "Web、Agent 与后台任务" : "服务未启动", status: health.started ? (health.degraded ? "降级" : "运行中") : "停止", good: health.started && !health.degraded },
    { name: "QQ / OneBot", detail: qq?.last_error || qq?.ws_url || "等待配置连接", status: qq?.status || "接口不可用", good: qq?.status === "connected" },
    ...(mcpServers ? (enabledMcp.length ? enabledMcp.map((item) => ({ name: `MCP · ${item.name}`, detail: item.last_error || item.transport, status: item.status, good: item.status === "ready" })) : [{ name: "MCP", detail: "尚未配置 MCP Server", status: "未配置", good: true }]) : [{ name: "MCP", detail: "状态接口不可用", status: "不可用", good: false }]),
    ...(skills ? [{ name: "Skills", detail: enabledSkills ? `${skillCount}/${enabledSkills} 可用` : "尚未启用 Skill", status: skills.some((item) => item.enabled && !item.available) ? "缺少依赖" : enabledSkills ? "正常" : "未配置", good: !skills.some((item) => item.enabled && !item.available) }] : [{ name: "Skills", detail: "状态接口不可用", status: "不可用", good: false }]),
    { name: "记忆任务", detail: `${health.memory_jobs?.completed ?? 0} 项已完成`, status: "后台运行", good: health.started },
  ];
  $("#service-health-list").innerHTML = healthRows.slice(0, 6).map((item) => `<div class="health-row"><span class="health-indicator ${item.good ? "good" : "warn"}"></span><div class="health-copy"><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.detail)}</small></div><span class="health-state">${escapeHtml(item.status)}</span></div>`).join("");
  $("#activity-summary").textContent = failed ? `有 ${failed} 条渠道事件失败，建议检查投递与运行日志。` : pending ? `最近 50 条记录中有 ${pending} 条事件正在等待处理。` : "最近 50 条渠道事件均已处理。";
  $("#overview-events").innerHTML = events.slice(0, 5).map((item) => `<div class="list-row"><span class="status-dot ${item.status}"></span><span class="row-main">${escapeHtml(item.status)}</span><small>${new Date(item.received_at).toLocaleString()}</small></div>`).join("") || `<p class="muted">${eventsResult.status === "fulfilled" ? "暂无渠道事件" : "事件接口不可用"}</p>`;
  state.providers = providers;
  state.channels = channels;
  state.mcp = mcpServers || [];
  state.skills = skills || [];
}

function go(view) {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  document.querySelectorAll(".view").forEach((item) => item.classList.toggle("active", item.id === `${view}-view`));
  if (view === "providers") loadProviders();
  if (view === "channels") loadQQ();
  if (view === "mcp") loadMcp();
  if (view === "skills") loadSkills();
  if (view === "diagnostics") loadDiagnostics();
  if (view === "memory") loadMemories();
}

function showError(error) { void dialogs.alert(error.message || String(error), "操作失败"); }

async function loadProviders() {
  const items = await json("/api/providers");
  const details = await Promise.all(items.map((item) => json(`/api/providers/${encodeURIComponent(item.name)}`)));
  $("#providers-list").innerHTML = items.length ? items.map((item, index) => { const detail = details[index]; return `<article class="manage-card"><div class="manage-card-head"><div><span class="eyebrow">${escapeHtml(item.provider_type)}</span><h2>${escapeHtml(item.name)}</h2></div><span class="status-pill ${item.enabled && item.configured ? "good" : "muted-pill"}">${item.enabled && item.configured ? "可用" : item.configured ? "已停用" : "未配置"}</span></div><p>${escapeHtml(detail.base_url || "默认 Base URL")} · ${detail.api_key_set ? "密钥已保存" : "未配置密钥"}</p><div class="simple-list">${detail.models.map((model) => `<div class="list-row"><span class="row-main">${escapeHtml(model.display_name)} <small>(${escapeHtml(model.model_name)}) · ${model.enabled ? "启用" : "停用"} · 工具 ${model.supports_tools ? "✓" : "—"} · 流式 ${model.supports_streaming ? "✓" : "—"} · 视觉 ${model.supports_vision ? "✓" : "—"} · 上下文 ${model.context_window ?? "默认"} · 输出 ${model.max_output_tokens ?? "默认"}</small></span><button class="quiet" data-model-edit="${escapeHtml(item.name)}" data-model-id="${escapeHtml(model.id)}">编辑</button><button class="danger-button" data-model-remove="${escapeHtml(item.name)}" data-model-id="${escapeHtml(model.id)}">删除</button></div>`).join("") || `<p class="muted">没有模型</p>`}</div><div class="card-actions"><button class="quiet" data-model-add="${escapeHtml(item.name)}">添加模型</button><button class="quiet" data-test-provider="${escapeHtml(item.name)}">测试连接</button><button class="quiet" data-default-provider="${escapeHtml(item.name)}">设为默认模型</button><button class="quiet" data-edit-provider="${escapeHtml(item.name)}">连接配置</button><button class="quiet" data-fallback-provider="${escapeHtml(item.name)}">故障切换</button><button class="quiet" data-toggle-provider="${escapeHtml(item.name)}" data-enabled="${item.enabled}">${item.enabled ? "停用" : "启用"}</button><button class="danger-button" data-remove-provider="${escapeHtml(item.name)}">删除</button></div></article>`; }).join("") : `<div class="empty-panel"><h2>还没有模型服务</h2><p>添加兼容的 Provider 后即可开始对话。</p></div>`;
  $("#providers-list").querySelectorAll("[data-test-provider]").forEach((button) => button.onclick = async () => { try { const result = await json(`/api/providers/${encodeURIComponent(button.dataset.testProvider)}/test`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }); dialogs.notify(`连接成功：${result.response}`); } catch (error) { showError(error); } });
  $("#providers-list").querySelectorAll("[data-default-provider]").forEach((button) => button.onclick = async () => { const item = items.find((provider) => provider.name === button.dataset.defaultProvider); const model = await dialogs.prompt(`输入要设为默认的模型：\n${item.models.join("\n")}`, item.models[0] || "", { title: "设置默认模型", placeholder: "选择或输入模型标识" }); if (!model) return; try { await json("/api/providers/default", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: item.name, model }) }); await loadRuntime(); } catch (error) { showError(error); } });
  $("#providers-list").querySelectorAll("[data-edit-provider]").forEach((button) => button.onclick = async () => {
    const name = button.dataset.editProvider;
    try {
      const detail = await json(`/api/providers/${encodeURIComponent(name)}`);
      const baseUrl = await dialogs.prompt("Base URL（留空使用默认地址）", detail.base_url || "", { title: "编辑 Provider · 连接地址" }); if (baseUrl === null) return;
      const apiKey = await dialogs.prompt("替换 API Key（留空表示不替换）", "", { title: "编辑 Provider · API Key", inputType: "password" }); if (apiKey === null) return;
      const apiKeyEnv = apiKey ? "" : await dialogs.prompt("改用 API Key 环境变量名（留空保留当前设置）", detail.api_key_env || "", { title: "编辑 Provider · 环境变量" }); if (apiKeyEnv === null) return;
      const clearApiKey = !apiKey && !apiKeyEnv && detail.api_key_set && await dialogs.confirm("是否清除当前保存的 API Key/环境变量引用？", "清除已保存密钥");
      await json(`/api/providers/${encodeURIComponent(name)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_url: baseUrl || null, enabled: detail.enabled, api_key: apiKey || null, api_key_env: apiKeyEnv || null, clear_api_key: clearApiKey }) });
      await loadProviders(); await loadRuntime();
    } catch (error) { showError(error); }
  });
  $("#providers-list").querySelectorAll("[data-fallback-provider]").forEach((button) => button.onclick = async () => {
    const name = button.dataset.fallbackProvider;
    try { const detail = await json(`/api/providers/${encodeURIComponent(name)}`); const value = await dialogs.prompt("按优先顺序填写备用 Provider 名称，用逗号分隔", detail.fallbacks.join(", "), { title: "配置故障切换", placeholder: "deepseek, openai" }); if (value === null) return; const providers = value.split(",").map((part) => part.trim()).filter(Boolean); await json(`/api/providers/${encodeURIComponent(name)}/fallbacks`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ providers }) }); await loadProviders(); }
    catch (error) { showError(error); }
  });
  $("#providers-list").querySelectorAll("[data-toggle-provider]").forEach((button) => button.onclick = async () => { try { const detail = await json(`/api/providers/${encodeURIComponent(button.dataset.toggleProvider)}`); await json(`/api/providers/${encodeURIComponent(button.dataset.toggleProvider)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_url: detail.base_url, enabled: button.dataset.enabled !== "true" }) }); await loadProviders(); await loadRuntime(); } catch (error) { showError(error); } });
  $("#providers-list").querySelectorAll("[data-remove-provider]").forEach((button) => button.onclick = async () => { if (!await dialogs.confirm(`删除 Provider「${button.dataset.removeProvider}」及其模型配置？`, "删除 Provider")) return; try { await json(`/api/providers/${encodeURIComponent(button.dataset.removeProvider)}`, { method: "DELETE" }); await loadProviders(); await loadRuntime(); } catch (error) { showError(error); } });
  $("#providers-list").querySelectorAll("[data-model-add]").forEach((button) => button.onclick = async () => { const modelName = await dialogs.prompt("模型标识（例如 deepseek-chat）", "", { title: "添加模型" }); if (!modelName) return; try { await json(`/api/providers/${encodeURIComponent(button.dataset.modelAdd)}/models`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_name: modelName, display_name: modelName }) }); await loadProviders(); } catch (error) { showError(error); } });
  $("#providers-list").querySelectorAll("[data-model-edit]").forEach((button) => button.onclick = async () => { const provider = button.dataset.modelEdit; const model = details.find((item) => item.name === provider)?.models.find((item) => item.id === button.dataset.modelId); if (!model) return; const editable = { model_name: model.model_name, display_name: model.display_name, enabled: model.enabled, supports_tools: model.supports_tools, supports_streaming: model.supports_streaming, supports_vision: model.supports_vision, context_window: model.context_window, max_output_tokens: model.max_output_tokens }; const raw = await dialogs.prompt("编辑模型配置（JSON）", JSON.stringify(editable, null, 2), { title: "编辑模型配置" }); if (raw === null) return; try { const values = JSON.parse(raw); await json(`/api/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model.id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values) }); await loadProviders(); } catch (error) { showError(error); } });
  $("#providers-list").querySelectorAll("[data-model-remove]").forEach((button) => button.onclick = async () => { if (!await dialogs.confirm("删除此模型配置？如果它是默认模型，将同时清除默认选择。", "删除模型")) return; try { await json(`/api/providers/${encodeURIComponent(button.dataset.modelRemove)}/models/${encodeURIComponent(button.dataset.modelId)}`, { method: "DELETE" }); await loadProviders(); await loadRuntime(); } catch (error) { showError(error); } });
}

async function loadQQ() {
  const [config, channels, groups] = await Promise.all([json("/api/qq/config"), json("/api/channels"), json("/api/qq/groups")]);
  const qq = channels.find((item) => item.channel === "qq");
  $("#qq-status-card").innerHTML = `<div class="panel-heading"><div><span class="eyebrow">CONNECTION STATUS</span><h2>NapCat / OneBot</h2></div><span class="status-pill ${qq?.status === "connected" ? "good" : "warn"}">${escapeHtml(qq?.status || "未连接")}</span></div><p>${escapeHtml(qq?.last_error || qq?.ws_url || "尚未配置连接")}</p>${config ? `<p class="muted">主人 QQ：${escapeHtml(config.owner_user_id || "未设置")} · Token：${config.token_readable ? "已保存" : "未配置"}</p>` : ""}`;
  const form = $("#qq-form");
  form.elements.endpoint.value = config?.endpoint || "ws://127.0.0.1:6199/ws";
  form.elements.owner_user_id.value = config?.owner_user_id || "";
  $("#groups-list").innerHTML = groups.map((group) => `<div class="list-row"><span class="row-main">${escapeHtml(group.group_id)}</span><small>${group.enabled ? "已允许" : "已禁用"} · ${group.require_mention ? "需 @" : "无需 @"}</small><button class="text-button" data-deny-group="${escapeHtml(group.group_id)}">移除</button></div>`).join("") || `<p class="muted">当前没有群聊白名单。私聊不受影响。</p>`;
  $("#groups-list").querySelectorAll("[data-deny-group]").forEach((button) => button.onclick = async () => { try { await json(`/api/qq/groups/${encodeURIComponent(button.dataset.denyGroup)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: false }) }); loadQQ(); } catch (error) { showError(error); } });
}

async function loadMcp() {
  const items = await json("/api/mcp/servers");
  $("#mcp-list").innerHTML = items.length ? items.map((item) => `<article class="manage-card"><div class="manage-card-head"><div><span class="eyebrow">${escapeHtml(item.transport)}</span><h2>${escapeHtml(item.name)}</h2></div><span class="status-pill ${item.status === "ready" ? "good" : item.enabled ? "warn" : "muted-pill"}">${escapeHtml(item.status)}</span></div><p>${escapeHtml(item.url || [item.command, ...(item.args || [])].filter(Boolean).join(" "))}</p><div class="meta-line">${item.capabilities?.tools ? "Tools" : ""} ${item.capabilities?.resources ? "· Resources" : ""} ${item.capabilities?.prompts ? "· Prompts" : ""} · 已授权工具 ${item.tool_allowlist?.length || 0} · Secret ${item.secret_names?.length || 0}</div>${item.last_error ? `<p class="error">${escapeHtml(item.last_error)}</p>` : ""}<div class="card-actions"><button class="quiet" data-mcp-config="${escapeHtml(item.name)}">编辑连接</button><button class="quiet" data-mcp-test="${escapeHtml(item.name)}">发现能力 / 测试</button><button class="quiet" data-mcp-secrets="${escapeHtml(item.name)}">密钥 / 环境变量</button><button class="quiet" data-mcp-auth="${escapeHtml(item.name)}">配置授权</button><button class="quiet" data-mcp-toggle="${escapeHtml(item.name)}" data-enabled="${item.enabled}">${item.enabled ? "停用" : "启用"}</button><button class="quiet" data-mcp-reconnect="${escapeHtml(item.name)}">重连</button><button class="danger-button" data-mcp-remove="${escapeHtml(item.name)}">移除</button></div></article>`).join("") : `<div class="empty-panel"><h2>尚未配置 MCP Server</h2><p>这里还没有 MCP 连接。添加后可在此测试连接、授权工具、配置密钥并查看状态。</p><button class="primary" data-start-mcp>添加第一个 MCP Server</button></div>`;
  $("#mcp-list").querySelector("[data-start-mcp]")?.addEventListener("click", () => $("#add-mcp").click());
  items.filter((item) => item.legacy_all_tools).forEach((item) => {
    const card = [...$("#mcp-list").querySelectorAll(".manage-card")].find((node) => node.querySelector("h2")?.textContent === item.name);
    card?.querySelector(".card-actions")?.insertAdjacentHTML("beforebegin", `<p class="error">此旧配置允许全部工具。点击“配置授权”可迁移为逐项白名单。</p>`);
  });
  $("#mcp-list").querySelectorAll("[data-mcp-test]").forEach((button) => button.onclick = async () => { try { const result = await json(`/api/mcp/servers/${encodeURIComponent(button.dataset.mcpTest)}/test`, { method: "POST" }); dialogs.notify(`连接测试成功：发现 ${result.tools?.length || 0} 个工具`); } catch (error) { showError(error); } });
  $("#mcp-list").querySelectorAll("[data-mcp-config]").forEach((button) => button.onclick = async () => { const name = button.dataset.mcpConfig; try { const detail = await json(`/api/mcp/servers/${encodeURIComponent(name)}`); const transport = await dialogs.prompt("传输类型：stdio / streamable_http / sse", detail.transport, { title: "编辑 MCP · 传输方式" }); if (!transport) return; let command = null, args = [], url = null; if (transport === "stdio") { command = await dialogs.prompt("启动命令", detail.command || "", { title: "编辑 MCP · 启动命令" }); if (!command) return; const argText = await dialogs.prompt("参数（JSON 数组）", JSON.stringify(detail.args || []), { title: "编辑 MCP · 启动参数" }); if (argText === null) return; args = JSON.parse(argText); } else { url = await dialogs.prompt("MCP Server URL", detail.url || "", { title: "编辑 MCP · 服务地址" }); if (!url) return; } await json("/api/mcp/servers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, transport, command, args, url, enabled: detail.enabled }) }); await loadMcp(); await loadRuntime(); } catch (error) { showError(error); } });
  $("#mcp-list").querySelectorAll("[data-mcp-toggle]").forEach((button) => button.onclick = async () => { try { await json(`/api/mcp/servers/${encodeURIComponent(button.dataset.mcpToggle)}/enabled`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: button.dataset.enabled !== "true" }) }); await loadMcp(); } catch (error) { showError(error); } });
  $("#mcp-list").querySelectorAll("[data-mcp-reconnect]").forEach((button) => button.onclick = async () => { try { await json(`/api/mcp/servers/${encodeURIComponent(button.dataset.mcpReconnect)}/reconnect`, { method: "POST" }); await loadMcp(); } catch (error) { showError(error); } });
  $("#mcp-list").querySelectorAll("[data-mcp-remove]").forEach((button) => button.onclick = async () => { if (!await dialogs.confirm(`移除 MCP ${button.dataset.mcpRemove}？已保存的连接配置和密钥引用也会一并移除。`, "移除 MCP Server")) return; try { await json(`/api/mcp/servers/${encodeURIComponent(button.dataset.mcpRemove)}`, { method: "DELETE" }); await loadMcp(); } catch (error) { showError(error); } });
  $("#mcp-list").querySelectorAll("[data-mcp-secrets]").forEach((button) => button.onclick = async () => {
    const name = button.dataset.mcpSecrets;
    try { const detail = await json(`/api/mcp/servers/${encodeURIComponent(name)}`);
      if (detail.secret_names?.length && await dialogs.confirm(`删除一个已保存的 Secret？\n${detail.secret_names.join("\n")}`, "删除 MCP 凭据")) {
        const ref = await dialogs.prompt("输入要删除的 Secret 名称", detail.secret_names[0], { title: "选择要删除的密钥" });
        if (ref) {
          if (ref.startsWith("env:")) await json(`/api/mcp/servers/${encodeURIComponent(name)}/env`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: ref.slice(4), value: null, secret: true }) });
          else if (ref.startsWith("header:")) await json(`/api/mcp/servers/${encodeURIComponent(name)}/header-secret`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: ref.slice(7), value: null }) });
        }
      }
      if (detail.transport === "stdio") { const pair = await dialogs.prompt(`设置普通环境变量 KEY=VALUE，删除用 -KEY（现有：${Object.keys(detail.env || {}).join(", ") || "无"}）`, "", { title: "普通环境变量" }); if (pair) { const remove = pair.startsWith("-"); const split = pair.indexOf("="); const key = remove ? pair.slice(1) : pair.slice(0, split); if (!key || (!remove && split < 1)) throw new Error("格式应为 KEY=VALUE 或 -KEY"); await json(`/api/mcp/servers/${encodeURIComponent(name)}/env`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, value: remove ? null : pair.slice(split + 1) }) }); }
        const secret = await dialogs.prompt("设置 Secret 环境变量，格式 KEY=VALUE（输入留空则跳过）", "", { title: "Secret 环境变量", inputType: "password" }); if (secret) { const split = secret.indexOf("="); if (split < 1) throw new Error("格式应为 KEY=VALUE"); await json(`/api/mcp/servers/${encodeURIComponent(name)}/env`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: secret.slice(0, split), value: secret.slice(split + 1), secret: true }) }); }
      } else { const header = await dialogs.prompt("HTTP Header 名称（例如 Authorization）", "", { title: "HTTP Header 名称" }); if (header) { const value = await dialogs.prompt("Header Secret 值", "", { title: "HTTP Header Secret", inputType: "password" }); if (value !== null) await json(`/api/mcp/servers/${encodeURIComponent(name)}/header-secret`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: header, value }) }); } }
      await loadMcp();
    } catch (error) { showError(error); }
  });
  $("#mcp-list").querySelectorAll("[data-mcp-auth]").forEach((button) => button.onclick = async () => {
    const name = button.dataset.mcpAuth;
    try { const found = await json(`/api/mcp/servers/${encodeURIComponent(name)}/test`, { method: "POST" });
      const tools = await dialogs.prompt(`授权工具名称，逗号分隔（发现：${(found.tools || []).join(", ")}）`, "", { title: "MCP 工具白名单" }); if (tools === null) return;
      await json(`/api/mcp/servers/${encodeURIComponent(name)}/tools/allowlist`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: tools.split(",").map((x) => x.trim()).filter(Boolean) }) });
      const resources = await dialogs.prompt(`授权 Resource URI/前缀，逗号分隔（发现：${(found.resources || []).map((x) => x.uri || x).join(", ")}）`, "", { title: "MCP Resource 白名单" }); if (resources !== null) await json(`/api/mcp/servers/${encodeURIComponent(name)}/resource/allowlist`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: resources.split(",").map((x) => x.trim()).filter(Boolean) }) });
      const prompts = await dialogs.prompt(`授权 Prompt 名称，逗号分隔（发现：${(found.prompts || []).map((x) => x.name || x).join(", ")}）`, "", { title: "MCP Prompt 白名单" }); if (prompts !== null) await json(`/api/mcp/servers/${encodeURIComponent(name)}/prompt/allowlist`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values: prompts.split(",").map((x) => x.trim()).filter(Boolean) }) });
      await loadMcp();
    } catch (error) { showError(error); }
  });
  $("#mcp-list").querySelectorAll("[data-mcp-test]").forEach((button) => {
    button.insertAdjacentHTML("afterend", `<button class="quiet" data-mcp-resource="${escapeHtml(button.dataset.mcpTest)}">读取 Resource</button><button class="quiet" data-mcp-prompt="${escapeHtml(button.dataset.mcpTest)}">运行 Prompt</button>`);
  });
  $("#mcp-list").querySelectorAll("[data-mcp-resource]").forEach((button) => button.onclick = async () => { try { const found = await json(`/api/mcp/servers/${encodeURIComponent(button.dataset.mcpResource)}/test`, { method: "POST" }); const choices = (found.resources || []).map((item) => item.uri); const uri = await dialogs.prompt(`Resource URI（须先授权）\n${choices.join("\n")}`, choices[0] || "", { title: "读取 MCP Resource" }); if (!uri) return; const result = await json(`/api/mcp/servers/${encodeURIComponent(button.dataset.mcpResource)}/resources/read`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ uri }) }); void dialogs.alert(`外部 MCP 内容（不可信文本）${result.truncated ? "，已截断" : ""}：\n${result.content.slice(0, 5000)}`, "Resource 内容 · 不可信文本"); } catch (error) { showError(error); } });
  $("#mcp-list").querySelectorAll("[data-mcp-prompt]").forEach((button) => button.onclick = async () => { try { const found = await json(`/api/mcp/servers/${encodeURIComponent(button.dataset.mcpPrompt)}/test`, { method: "POST" }); const choices = (found.prompts || []).map((item) => item.name); const promptName = await dialogs.prompt(`Prompt 名称（须先授权）\n${choices.join("\n")}`, choices[0] || "", { title: "运行 MCP Prompt" }); if (!promptName) return; const raw = await dialogs.prompt("Prompt 参数 JSON", "{}", { title: "填写 Prompt 参数" }); if (raw === null) return; const result = await json(`/api/mcp/servers/${encodeURIComponent(button.dataset.mcpPrompt)}/prompts/render`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: promptName, arguments: JSON.parse(raw) }) }); void dialogs.alert(`外部 MCP 内容（不可信文本）${result.truncated ? "，已截断" : ""}：\n${result.content.slice(0, 5000)}`, "Prompt 结果 · 不可信文本"); } catch (error) { showError(error); } });
}

async function loadSkills() {
  const [items, trash] = await Promise.all([json("/api/skills"), json("/api/skills/trash")]);
  $("#skills-list").innerHTML = items.length ? items.map((item) => `<article class="manage-card"><div class="manage-card-head"><div><span class="eyebrow">${escapeHtml(item.source_type || "本地")}${item.revision ? ` · ${escapeHtml(item.revision)}` : ""}</span><h2>${escapeHtml(item.name)}</h2></div><span class="status-pill ${item.enabled && item.available ? "good" : "muted-pill"}">${item.enabled ? item.available ? "已启用" : "缺少依赖" : "已停用"}</span></div><p>${escapeHtml(item.description || item.error || "暂无描述")}</p><div class="meta-line">工具依赖：${(item.required_tools || []).map(escapeHtml).join("、") || "无"} · 命令依赖：${(item.missing_bins || []).map(escapeHtml).join("、") || "满足"}${item.modified ? " · 本地内容有修改" : ""}</div><div class="card-actions">${item.managed ? `<button class="quiet" data-skill-toggle="${escapeHtml(item.name)}" data-enabled="${item.enabled}">${item.enabled ? "停用" : "启用"}</button><button class="quiet" data-skill-update="${escapeHtml(item.name)}">检查更新</button><button class="danger-button" data-skill-remove="${escapeHtml(item.name)}">移入回收站</button>` : `<span class="muted">由本地目录提供</span>`}</div></article>`).join("") : `<div class="empty-panel"><h2>还没有可用 Skill</h2><p>安装本地 Skill 文件夹后，可在这里启停、更新和恢复 Skill。</p><button class="primary" data-start-skill>安装第一个 Skill</button></div>`;
  $("#skills-list").querySelector("[data-start-skill]")?.addEventListener("click", () => $("#install-skill").click());
  $("#skills-trash").innerHTML = trash.length ? trash.map((item) => `<div class="list-row"><span class="row-main">${escapeHtml(item.name)}</span><small>${escapeHtml(item.source_type)} · ${escapeHtml(item.trashed_at || "")}</small><button class="quiet" data-skill-restore="${escapeHtml(item.name)}">恢复</button></div>`).join("") : `<p class="muted">回收站为空</p>`;
  $("#skills-list").querySelectorAll("[data-skill-toggle]").forEach((button) => button.onclick = async () => { try { await json(`/api/skills/${encodeURIComponent(button.dataset.skillToggle)}/enabled`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: button.dataset.enabled !== "true" }) }); await loadSkills(); } catch (error) { showError(error); } });
  $("#skills-list").querySelectorAll("[data-skill-remove]").forEach((button) => button.onclick = async () => { if (!await dialogs.confirm(`将 ${button.dataset.skillRemove} 移入回收站？`, "移入 Skills 回收站")) return; try { await json(`/api/skills/${encodeURIComponent(button.dataset.skillRemove)}`, { method: "DELETE" }); await loadSkills(); } catch (error) { showError(error); } });
  $("#skills-list").querySelectorAll("[data-skill-update]").forEach((button) => button.onclick = async () => { const name = button.dataset.skillUpdate; try { const skill = items.find((item) => item.name === name); if (skill.modified && !await dialogs.confirm("此 Skill 有本地修改；应用更新会覆盖当前安装目录的文件。是否继续预览？", "Skill 有本地修改")) return; const ref = await dialogs.prompt("目标 Git 分支或 Tag（留空使用原来源）", "", { title: "检查 Skill 更新" }); if (ref === null) return; const body = JSON.stringify({ ref: ref || null }); const preview = await json(`/api/skills/${encodeURIComponent(name)}/update-preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body }); const changes = (preview.changed_files || []).slice(0, 30).join("\n"); if (!preview.changed) { dialogs.notify("已是最新版本。"); return; } if (!await dialogs.confirm(`更新 Skill「${name}」？\nRevision：${preview.old_revision || "未知"} → ${preview.new_revision || "未知"}\n文件变化：\n${changes}${preview.changed_files.length > 30 ? "\n…" : ""}`, "确认更新 Skill")) return; await json(`/api/skills/${encodeURIComponent(name)}/update`, { method: "POST", headers: { "Content-Type": "application/json" }, body }); await loadSkills(); await loadRuntime(); } catch (error) { showError(error); } });
  $("#skills-trash").querySelectorAll("[data-skill-restore]").forEach((button) => button.onclick = async () => { try { await json(`/api/skills/${encodeURIComponent(button.dataset.skillRestore)}/restore`, { method: "POST" }); await loadSkills(); await loadRuntime(); } catch (error) { showError(error); } });
}

async function loadDiagnostics() {
  const [events, deliveries] = await Promise.all([json("/api/channel-events?limit=100"), json("/api/channel-deliveries?limit=100")]);
  $("#diagnostic-events").innerHTML = events.length ? events.map((item) => `<div class="table-row"><div><strong>${escapeHtml(item.status)}</strong><small>${escapeHtml(item.id)}</small></div><small>${new Date(item.received_at).toLocaleString()}</small><small>${escapeHtml(item.last_error || "—")}</small>${["failed", "pending"].includes(item.status) ? `<button class="quiet" data-replay="${escapeHtml(item.id)}">重放</button>` : ""}</div>`).join("") : `<p class="muted">暂无事件记录</p>`;
  $("#diagnostic-deliveries").innerHTML = deliveries.length ? deliveries.map((item) => `<div class="table-row"><div><strong>${escapeHtml(item.status)}</strong><small>${escapeHtml(item.id)}</small></div><small>${escapeHtml(item.provider_message_id || "无外部消息 ID")}</small><small>${escapeHtml(item.error || "—")}</small>${["failed", "unknown"].includes(item.status) ? `<button class="quiet" data-retry="${escapeHtml(item.id)}">${item.status === "unknown" ? "确认重试" : "重试"}</button>` : ""}</div>`).join("") : `<p class="muted">暂无投递记录</p>`;
  $("#diagnostic-events").querySelectorAll("[data-replay]").forEach((button) => button.onclick = async () => { try { await json(`/api/channel-events/${encodeURIComponent(button.dataset.replay)}/replay`, { method: "POST" }); await loadDiagnostics(); } catch (error) { showError(error); } });
  $("#diagnostic-deliveries").querySelectorAll("[data-retry]").forEach((button) => button.onclick = async () => { const unknown = button.textContent.includes("确认"); if (unknown && !await dialogs.confirm("发送结果未知，QQ 可能已经收到。仍要再次发送吗？", "确认再次投递")) return; try { await json(`/api/channel-deliveries/${encodeURIComponent(button.dataset.retry)}/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ allow_unknown: unknown }) }); await loadDiagnostics(); } catch (error) { showError(error); } });
}

async function loadConversations() {
  const items = await json("/api/conversations");
  const list = $("#conversations");
  list.innerHTML = items.map((item) => `
    <button class="conversation ${item.id === state.conversationId ? "active" : ""}"
      data-id="${item.id}" data-title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</button>
  `).join("");
  list.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => openConversation(button.dataset.id, button.dataset.title));
  });
}

async function openConversation(id, title) {
  state.conversationId = id;
  $("#conversation-title").textContent = title || "会话";
  const items = await json(`/api/conversations/${id}/messages`);
  messages.innerHTML = "";
  items.forEach((item) => addMessage(item.role === "user" ? "user" : "assistant", item.content));
  await loadConversations();
}

async function sendMessage(text) {
  state.busy = true;
  send.disabled = true;
  addMessage("user", text);
  const assistant = addMessage("assistant", "");
  activity.textContent = "正在思考";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation_id: state.conversationId })
    });
    if (!response.ok || !response.body) throw new Error("无法启动对话");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";
      for (const block of blocks) {
        const line = block.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "run") state.conversationId = event.conversation_id;
        if (event.type === "chunk") assistant.textContent += event.text;
        if (event.type === "tool") activity.textContent = `工具 · ${event.name} · ${event.status}`;
        if (event.type === "step") activity.textContent = event.name;
        if (event.type === "error") throw new Error(event.error);
        if (event.type === "done") {
          state.conversationId = event.conversation_id;
          if (!assistant.textContent) assistant.textContent = event.response;
        }
      }
      if (done) break;
    }
    activity.textContent = "";
    await loadConversations();
  } catch (error) {
    assistant.textContent = `运行失败：${error.message}`;
    assistant.parentElement.classList.add("error");
    activity.textContent = "";
  } finally {
    state.busy = false;
    send.disabled = false;
    input.focus();
  }
}

async function loadMemories() {
  const query = $("#memory-search").value.trim();
  const tier = $("#memory-tier").value;
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (tier) params.set("tier", tier);
  const items = await json(`/api/memories?${params}`);
  $("#memory-count").textContent = `${items.length} 条`;
  const list = $("#memories");
  list.innerHTML = items.length ? items.map((item) => `
    <article class="memory-card">
      <header><span>${escapeHtml(item.type)} · ${escapeHtml(item.tier)}</span><span>${escapeHtml(item.origin)}</span></header>
      <p>${escapeHtml(item.content)}</p>
      <button data-id="${item.id}" data-content="${escapeHtml(item.content)}">纠正</button>
    </article>
  `).join("") : "<p>没有匹配的记忆。</p>";
  list.querySelectorAll("button").forEach((button) => button.addEventListener("click", async () => {
    const content = await dialogs.prompt("修改记忆内容", button.dataset.content, { title: "纠正长期记忆" });
    if (!content || content === button.dataset.content) return;
    await json(`/api/memories/${button.dataset.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content })
    });
    await loadMemories();
  }));
}

$("#composer").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || state.busy) return;
  input.value = "";
  await sendMessage(text);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#composer").requestSubmit();
  }
});

$("#new-chat").addEventListener("click", () => {
  state.conversationId = null;
  $("#conversation-title").textContent = "新的对话";
  messages.innerHTML = `<div class="empty-state"><span>知</span><h2>新的对话</h2><p>长期记忆仍然会在不同会话间保持连续。</p></div>`;
  loadConversations();
});

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => {
  go(button.dataset.view);
}));

document.querySelectorAll("[data-goto]").forEach((button) => button.addEventListener("click", () => go(button.dataset.goto)));
document.querySelectorAll("[data-refresh]").forEach((button) => button.addEventListener("click", async () => {
  await loadRuntime();
  if ($("#diagnostics-view").classList.contains("active")) await loadDiagnostics();
}));

$("#add-provider").addEventListener("click", async () => {
  const form = await dialogs.form("添加模型服务", "API Key 会保存在系统密钥存储中；此处填写的密钥不会再次显示。", [
    { name: "name", label: "显示名称", required: true, placeholder: "例如 deepseek" },
    { name: "provider_type", label: "Provider 类型", type: "select", value: "deepseek", options: [{ value: "deepseek", label: "DeepSeek" }, { value: "minimax", label: "MiniMax" }, { value: "kimi", label: "Kimi / Moonshot" }, { value: "openai", label: "OpenAI 兼容" }, { value: "anthropic", label: "Anthropic" }] },
    { name: "api_key", label: "API Key", type: "password", placeholder: "仅本次提交" },
    { name: "api_key_env", label: "API Key 环境变量", placeholder: "如 OPENAI_API_KEY", description: "和 API Key 二选一。" },
    { name: "base_url", label: "自定义 Base URL（可选）", type: "url", placeholder: "留空使用默认地址" },
  ], "保存 Provider");
  if (!form) return;
  try {
    if (form.api_key && form.api_key_env) throw new Error("API Key 和环境变量只能填写一个。");
    await json("/api/providers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: String(form.name).trim(), provider_type: form.provider_type, api_key: form.api_key || null, api_key_env: form.api_key_env || null, base_url: form.base_url || null }) });
    dialogs.notify("Provider 已保存"); await loadProviders(); await loadRuntime();
  } catch (error) { showError(error); }
});

$("#qq-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget;
  try {
    await json("/api/qq/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ endpoint: form.elements.endpoint.value, owner_user_id: form.elements.owner_user_id.value || null, token: form.elements.token.value || null }) });
    form.elements.token.value = ""; await loadQQ(); await loadRuntime(); dialogs.notify("QQ 配置已保存");
  } catch (error) { showError(error); }
});
$("#qq-start").addEventListener("click", async () => { try { await json("/api/qq/start", { method: "POST" }); await loadQQ(); await loadRuntime(); } catch (error) { showError(error); } });
$("#qq-stop").addEventListener("click", async () => { try { await json("/api/qq/stop", { method: "POST" }); await loadQQ(); await loadRuntime(); } catch (error) { showError(error); } });
$("#group-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const form = event.currentTarget; const group = form.elements.group_id.value.trim();
  try { await json(`/api/qq/groups/${encodeURIComponent(group)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: true, require_mention: form.elements.require_mention.checked }) }); form.reset(); form.elements.require_mention.checked = true; await loadQQ(); } catch (error) { showError(error); }
});

$("#add-mcp").addEventListener("click", async () => {
  const form = await dialogs.form("添加 MCP 服务", "新服务默认关闭。连接成功后，先检查服务能力，再逐项授权给 Agent。", [
    { name: "name", label: "服务名称", required: true, placeholder: "例如 filesystem" },
    { name: "transport", label: "连接方式", type: "select", value: "stdio", options: [{ value: "stdio", label: "本机进程（stdio）" }, { value: "streamable_http", label: "远程服务（Streamable HTTP）" }, { value: "sse", label: "远程服务（SSE）" }] },
    { name: "command", label: "启动命令", required: true, placeholder: "例如 npx 或 uvx", description: "命令需已安装在本机。", dependsOn: { name: "transport", value: "stdio" } },
    { name: "args", label: "启动参数（JSON 字符串数组）", type: "textarea", value: "[]", placeholder: '["-y", "@example/mcp-server"]', dependsOn: { name: "transport", value: "stdio" } },
    { name: "url", label: "服务 URL", type: "url", required: true, placeholder: "https://example.com/mcp", description: "远程 MCP 使用 HTTPS；本机回环地址可使用 HTTP。", dependsOn: { name: "transport", value: "streamable_http" } },
    { name: "sse_url", label: "SSE 服务 URL", type: "url", required: true, placeholder: "https://example.com/sse", dependsOn: { name: "transport", value: "sse" } },
  ], "添加服务");
  if (!form) return;
  try {
    const transport = String(form.transport);
    let args = [];
    if (transport === "stdio") {
      args = JSON.parse(String(form.args || "[]"));
      if (!Array.isArray(args) || args.some((item) => typeof item !== "string")) throw new Error('启动参数必须是字符串数组，例如 ["-y", "package"]');
    }
    await json("/api/mcp/servers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      name: String(form.name).trim(), transport,
      command: transport === "stdio" ? String(form.command).trim() : null,
      args, url: transport === "stdio" ? null : transport === "sse" ? String(form.sse_url).trim() : String(form.url).trim(), enabled: false,
    }) });
    dialogs.notify("MCP 服务已添加"); await loadMcp(); await loadRuntime();
  } catch (error) { showError(error); }
});

$("#install-skill").addEventListener("click", async () => {
  const source = await dialogs.prompt("填写 Skill 本地目录路径或 HTTPS Git 仓库地址", "", { title: "安装 Skill", placeholder: "https://github.com/owner/repo" }); if (!source) return;
  try {
    const preview = await json("/api/skills/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }) });
    const warnings = (preview.warnings || []).join("\n");
    if (!await dialogs.confirm(`安装 Skill「${preview.name}」？\n${preview.description || "无描述"}\n${preview.files.length} 个文件\n${warnings}`, "确认安装 Skill")) return;
    await json("/api/skills/install", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }) }); await loadSkills(); await loadRuntime();
  } catch (error) { showError(error); }
});

let searchTimer;
$("#memory-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadMemories, 180);
});
$("#memory-tier").addEventListener("change", loadMemories);

await Promise.all([loadRuntime(), loadConversations()]);
