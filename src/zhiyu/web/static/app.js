const state = { conversationId: null, busy: false };

const $ = (selector) => document.querySelector(selector);
const messages = $("#messages");
const activity = $("#activity");
const input = $("#message-input");
const send = $("#send");

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
  try {
    const [health, providers, channels, events] = await Promise.all([
      json("/api/health"), json("/api/providers"), json("/api/channels"),
      json("/api/channel-events?limit=50")
    ]);
    $("#health-dot").classList.add("ok");
    $("#health-text").textContent = "本地服务运行中";
    const qq = channels.find((item) => item.channel === "qq");
    const failed = events.filter((item) => item.status === "failed").length;
    const pending = events.filter((item) => ["pending", "processing", "responded"].includes(item.status)).length;
    const qqStatus = qq?.status === "connected" ? "QQ 已连接" : `QQ ${qq?.status || "未连接"}`;
    $("#runtime-detail").textContent = `${qqStatus} · 待处理 ${pending} · 失败 ${failed}`;
    const first = providers.find((item) => item.enabled && item.configured);
    $("#model-badge").textContent = first ? `${first.name} · ${first.models[0] || "未选模型"}` : "未配置模型";
    if (!health.started) $("#health-text").textContent = "服务正在启动";
  } catch (error) {
    $("#health-text").textContent = "连接失败";
    $("#runtime-detail").textContent = error.message;
  }
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
    const content = window.prompt("修改记忆", button.dataset.content);
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
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item === button));
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  $(`#${button.dataset.view}-view`).classList.add("active");
  if (button.dataset.view === "memory") loadMemories();
}));

let searchTimer;
$("#memory-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadMemories, 180);
});
$("#memory-tier").addEventListener("change", loadMemories);

await Promise.all([loadRuntime(), loadConversations()]);
