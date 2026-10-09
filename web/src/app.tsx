import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { AgentScope } from "./agentScope";
import { AgentsPage } from "./pages/AgentsPage";
import { AgentAboutPage } from "./pages/AgentAboutPage";
import { createRoot } from "react-dom/client";
import { deriveOverview, type ApiResult } from "./overview";
import { errorText, post, request } from "./api";
import { StateCard } from "./components/StateCard";
import { ChatPage } from "./pages/ChatPage";
import { MemoryPage } from "./pages/MemoryPage";
import { AboutEachOtherPage } from "./pages/AboutEachOtherPage";
import { useChatSession } from "./hooks/useChatSession";
import { useManagementActions } from "./hooks/useManagementActions";
import { OverviewPage } from "./pages/OverviewPage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { ChannelsPage } from "./pages/ChannelsPage";
import { McpPage } from "./pages/McpPage";
import { SkillsPage } from "./pages/SkillsPage";
import type { Item, Page } from "./types";
import "./app.css";

const nav: { id: Page; icon: string; label: string }[] = [
  { id: "overview", icon: "⌂", label: "运行总览" },
  { id: "chat", icon: "◌", label: "对话" },
  { id: "agents", icon: "◎", label: "智能体" },
  { id: "about", icon: "✧", label: "关于彼此" },
  { id: "providers", icon: "◈", label: "模型服务" },
  { id: "channels", icon: "⌁", label: "QQ 渠道" },
  { id: "plugins", icon: "◇", label: "插件" },
  { id: "diagnostics", icon: "⌘", label: "运行诊断" },
  { id: "memory", icon: "✳", label: "日记" },
];
const titles: Record<Page, string> = {
  overview: "运行总览",
  chat: "对话",
  agents: "智能体",
  providers: "模型服务",
  channels: "QQ 渠道",
  plugins: "插件",
  diagnostics: "运行诊断",
  about: "关于彼此",
  memory: "日记",
};
const safe = async <T,>(promise: Promise<T>): Promise<ApiResult<T>> => {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
};
function App() {
  const [page, setPage] = useState<Page>(() => {
    const raw = new URLSearchParams(location.search).get("page");
    const value = (raw === "mcp" || raw === "skills" ? "plugins" : raw === "profile" ? "about" : raw) as Page;
    return nav.some((item) => item.id === value) ? value : "overview";
  });
  const [pluginTab, setPluginTab] = useState<"mcp" | "skills">(() => {
    const params = new URLSearchParams(location.search);
    return params.get("page") === "skills" || params.get("tab") === "skills"
      ? "skills" : "mcp";
  });
  const [overview, setOverview] = useState<ReturnType<
    typeof deriveOverview
  > | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [conversations, setConversations] = useState<Item[]>([]);
  const conversationsRef = useRef<Item[]>([]);
  conversationsRef.current = conversations;
  const [conversationId, setConversationId] = useState<string | null>(() =>
    new URLSearchParams(location.search).get("conversation"),
  );
  const [conversationTitle, setConversationTitle] = useState("新的对话");
  const [pageRevision, setPageRevision] = useState(0);
  const [pageError, setPageError] = useState("");
  const [agents, setAgents] = useState<Item[]>([]);
  const [characterId, setCharacterId] = useState<string | null>(() => new URLSearchParams(location.search).get("agent"));
  const currentAgent = agents.find((item) => item.id === characterId);
  const agentName = currentAgent?.name || "星栖";
  const refreshAgents = useCallback(async () => setAgents(await request<Item[]>("/api/agents")), []);
  const conversationLoadRef = useRef(0);

  const refreshOverview = useCallback(async () => {
    setOverviewLoading(true);
    const [
      health,
      providerList,
      defaultModel,
      channelList,
      eventList,
      mcpList,
      skillList,
      qqConfig,
    ] = await Promise.all([
      safe(request<Item>("/api/health")),
      safe(request<Item[]>("/api/providers")),
      safe(request<Item>("/api/providers/default")),
      safe(request<Item[]>("/api/channels")),
      safe(request<Item[]>("/api/channel-events?limit=50")),
      safe(request<Item[]>("/api/mcp/servers")),
      safe(request<Item[]>("/api/skills")),
      safe(request<Item>("/api/qq/config")),
    ]);
    setOverview(
      deriveOverview({
        health,
        providers: providerList,
        defaultModel,
        channels: channelList,
        events: eventList,
        mcp: mcpList,
        skills: skillList,
        qqConfig,
      }),
    );
    setOverviewLoading(false);
  }, []);

  const refreshConversations = useCallback(
    async () => {
      setConversations(await request<Item[]>("/api/conversations"));
      await refreshAgents();
    },
    [refreshAgents],
  );
  const onConversationCreated = useCallback((id: string) => {
    setConversationId(id);
    setConversationTitle("新对话");
    history.replaceState(
      {},
      "",
      `/?page=chat&conversation=${encodeURIComponent(id)}`,
    );
  }, []);
  const onChatErrorClear = useCallback(() => setPageError(""), []);
  const reportPageError = useCallback((error: string) => setPageError(error), []);
  const closeMobileMenu = useCallback(() => {
    document.querySelector(".sidebar")?.classList.remove("menu-open");
  }, []);
  const {
    messages,
    setMessages,
    draft,
    setDraft,
    busy,
    activity,
    setActivity,
    sendMessage,
    cancelRun,
    clearMessages,
  } = useChatSession({
    conversationId,
    characterId,
    refreshConversations,
    onConversationCreated,
    onErrorClear: onChatErrorClear,
    onRequestError: reportPageError,
  });
  const deleteConversation = useCallback(async (item: Item) => {
    const confirmed = await window.zhiyuDialogs.confirm(
      "删除后会移除这段会话的聊天记录和运行记录，已沉淀的长期记忆会保留。",
      "删除会话",
    );
    if (!confirmed) return;
    try {
      if (item.id === conversationId) await cancelRun();
      await request(`/api/conversations/${encodeURIComponent(item.id)}`, post("DELETE"));
      await refreshConversations();
      if (item.id === conversationId) {
        conversationLoadRef.current += 1;
        setConversationId(null);
        setConversationTitle("新的对话");
        clearMessages();
        setActivity("");
        setPage("chat");
        history.replaceState({}, "", "/?page=chat");
      }
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "删除失败");
    }
  }, [cancelRun, clearMessages, conversationId, refreshConversations, setActivity]);
  const openConversation = useCallback(
    async (id: string, title?: string) => {
      closeMobileMenu();
      await cancelRun();
      setActivity("");
      const loadId = ++conversationLoadRef.current;
      const all = conversationsRef.current.length ? conversationsRef.current : await request<Item[]>("/api/conversations");
      const stored = all.find((item) => item.id === id);
      if (stored) setCharacterId(stored.character_id || null);
      setConversationId(id);
      setConversationTitle(title || "会话");
      setPage("chat");
      history.pushState(
        {},
        "",
        `/?page=chat&conversation=${encodeURIComponent(id)}`,
      );
      const rows = await request<Item[]>(
        `/api/conversations/${encodeURIComponent(id)}/messages`,
      );
      if (loadId === conversationLoadRef.current)
        setMessages(
          rows.map((row) => ({
            ...row,
            role: row.role === "user" ? "user" : "assistant",
          })),
        );
    },
    [cancelRun, closeMobileMenu],
  );
  const startNewChat = useCallback(async () => {
    closeMobileMenu();
    await cancelRun();
    conversationLoadRef.current += 1;
    setConversationId(null);
    setConversationTitle("新的对话");
    clearMessages();
    setActivity("");
    setPage("chat");
    history.pushState({}, "", `/?page=chat${characterId ? `&agent=${encodeURIComponent(characterId)}` : ""}`);
  }, [cancelRun, clearMessages, closeMobileMenu, characterId]);
  const selectAgent = useCallback(async (id: string | null) => {
    await startNewChat();
    setCharacterId(id);
    setPageError("");
    setDraft("");
    history.replaceState({}, "", `/?page=chat${id ? `&agent=${encodeURIComponent(id)}` : ""}`);
  }, [startNewChat, setDraft]);

  const navigate = useCallback(
    async (target: Page) => {
      closeMobileMenu();
      if (busy && target !== "chat") await cancelRun();
      setPage(target);
      setPageError("");
      setPageRevision((value) => value + 1);
      history.pushState(
        {},
        "",
        target === "overview" ? `/${characterId ? `?agent=${encodeURIComponent(characterId)}` : ""}` : target === "plugins"
          ? `/?page=plugins&tab=${pluginTab}${characterId ? `&agent=${encodeURIComponent(characterId)}` : ""}` : `/?page=${target}${characterId ? `&agent=${encodeURIComponent(characterId)}` : ""}`,
      );
    },
    [busy, cancelRun, closeMobileMenu, pluginTab, characterId],
  );

  function selectPluginTab(tab: "mcp" | "skills") {
    setPluginTab(tab);
    setPageError("");
    history.pushState({}, "", `/?page=plugins&tab=${tab}${characterId ? `&agent=${encodeURIComponent(characterId)}` : ""}`);
  }

  useEffect(() => {
    void refreshOverview();
    void refreshConversations();
    void refreshAgents().catch((error) => setPageError(errorText(error)));
    const onPop = () => {
      closeMobileMenu();
      const params = new URLSearchParams(location.search);
      const raw = params.get("page") || "overview";
      const target = (raw === "mcp" || raw === "skills" ? "plugins" : raw === "profile" ? "about" : raw) as Page;
      const id = params.get("conversation");
      if (target === "plugins")
        setPluginTab(raw === "skills" || params.get("tab") === "skills" ? "skills" : "mcp");
      setPage(nav.some((item) => item.id === target) ? target : "overview");
      setConversationId(id);
      setCharacterId(params.get("agent"));
      if (id)
        void (async () => {
          const loadId = ++conversationLoadRef.current;
          await cancelRun();
          const rows = await request<Item[]>(
            `/api/conversations/${encodeURIComponent(id)}/messages`,
          );
          if (loadId !== conversationLoadRef.current) return;
          setMessages(
            rows.map((row) => ({
              ...row,
              role: row.role === "user" ? "user" : "assistant",
            })),
          );
          setCharacterId(conversationsRef.current.find((item) => item.id === id)?.character_id || null);
          setConversationTitle(
            conversationsRef.current.find((item) => item.id === id)?.title ||
              "会话",
          );
        })().catch((error) => setPageError(errorText(error)));
      else if (target === "chat") {
        void cancelRun();
        clearMessages();
        setConversationTitle("新的对话");
      }
    };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, [refreshOverview, refreshConversations, cancelRun, clearMessages, closeMobileMenu]);
  useEffect(() => {
    const id = new URLSearchParams(location.search).get("conversation");
    if (id)
      void openConversation(id).catch((error) =>
        setPageError(errorText(error)),
      );
    // URL synchronization is intentionally triggered only by the initial/deep-linked conversation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const act = useCallback(async (action: () => Promise<unknown>, refresh = true) => {
    try {
      await action();
      if (refresh) await refreshOverview();
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "操作失败");
    }
  }, [refreshOverview]);
  const onManagementChanged = useCallback(
    () => setPageRevision((value) => value + 1),
    [],
  );
  const { addProvider, addMcp, installSkill } = useManagementActions(
    act,
    onManagementChanged,
    characterId,
  );

  const pageBody = (() => {
    if (page === "agents") return <AgentsPage agents={agents} selectedId={characterId} onSelect={selectAgent} onChanged={refreshAgents} />;
    if (page === "overview")
      return (
        <OverviewPage
          overview={overview}
          overviewLoading={overviewLoading}
          refreshOverview={refreshOverview}
          navigate={navigate}
        />
      );
    if (page === "providers")
      return (
        <ProvidersPage
          reloadKey={pageRevision}
          onLoadError={reportPageError}
          act={act}
          addProvider={addProvider}
        />
      );
    if (page === "channels")
      return (
        <ChannelsPage
          reloadKey={pageRevision}
          onLoadError={reportPageError}
          act={act}
        />
      );
    if (page === "plugins")
      return (
        <div className="plugins-page">
          <div className="plugin-tabs" role="tablist" aria-label="插件类型">
            <button role="tab" aria-selected={pluginTab === "mcp"}
              onClick={() => selectPluginTab("mcp")}>MCP 服务</button>
            <button role="tab" aria-selected={pluginTab === "skills"}
              onClick={() => selectPluginTab("skills")}>Skills</button>
          </div>
          <div role="tabpanel" aria-label={pluginTab === "mcp" ? "MCP 服务" : "Skills"}>
            {pluginTab === "mcp" ? (
              <McpPage reloadKey={pageRevision} onLoadError={reportPageError}
                act={act} addMcp={addMcp} />
            ) : (
              <SkillsPage reloadKey={pageRevision} onLoadError={reportPageError}
                act={act} installSkill={installSkill} />
            )}
          </div>
        </div>
      );
    if (page === "diagnostics")
      return (
        <DiagnosticsPage
          reloadKey={pageRevision}
          onLoadError={reportPageError}
          act={act}
        />
      );
    if (page === "about")
      return (
        characterId ? (currentAgent ? <AgentAboutPage agent={currentAgent} reloadKey={pageRevision} onLoadError={reportPageError} /> : <StateCard title="智能体不存在或正在加载" />) : <AboutEachOtherPage
          reloadKey={pageRevision}
          onLoadError={reportPageError}
        />
      );
    return null;
  })();

  const currentStatus = overview?.health?.started
    ? overview.health.degraded
      ? "部分降级"
      : "运行正常"
    : overview
      ? "未运行"
      : "检查中";
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-content">
          <div className="brand">
            <span className="brand-mark">星</span>
            <div>
              <strong>星栖</strong>
              <small>Personal Agent</small>
            </div>
            <button
              className="mobile-menu"
              aria-label="折叠菜单"
              onClick={(event) =>
                event.currentTarget
                  .closest(".sidebar")
                  ?.classList.toggle("menu-open")
              }
            >
              ☰
            </button>
          </div>
          <label className="agent-selector">
            <span>当前智能体</span>
            <select aria-label="选择智能体" value={characterId || ""} onChange={(event) => void selectAgent(event.target.value || null)}>
              <option value="">星栖 · 默认助手</option>
              {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
          </label>
          <button className="primary wide" onClick={() => void startNewChat()}>
            新对话
          </button>
          <nav className="nav" aria-label="主导航">
            {nav.map((item) => (
              <button
                key={item.id}
                className={`nav-item ${page === item.id ? "active" : ""}`}
                onClick={() => void navigate(item.id)}
              >
                <span>{item.icon}</span>
                {item.label}
              </button>
            ))}
          </nav>
          <div className="section-title">最近会话</div>
          <div className="conversation-list">
            {conversations.filter((item) => (item.character_id || null) === characterId).slice(0, 30).map((item) => (
              <div className="conversation-row" key={item.id}>
                <button
                  className={`conversation ${item.id === conversationId ? "active" : ""}`}
                  onClick={() => void openConversation(item.id, item.title)}
                >
                  {item.title || "未命名会话"}
                </button>
                <button
                  className="conversation-delete"
                  aria-label={`删除会话：${item.title || "未命名会话"}`}
                  title="删除会话"
                  onClick={() => void deleteConversation(item)}
                >
                  删除
                </button>
              </div>
            ))}
            {!conversations.some((item) => (item.character_id || null) === characterId) && (
              <small className="muted sidebar-empty">暂无会话</small>
            )}
          </div>
        </div>
        <div className="runtime-card">
          <span
            className={`dot ${overview?.health?.started ? "ok" : ""}`}
          ></span>
          <div>
            <strong>{currentStatus}</strong>
            <small>
              {overview?.model?.model
                ? `${overview.model.provider} · ${overview.model.model}`
                : "本机运行实例"}
            </small>
          </div>
        </div>
      </aside>
      <AgentScope.Provider value={characterId}>
      <main className="main" key={characterId || "default"}>
        {page === "chat" ? (
          <ChatPage
            agentName={agentName}
            conversationTitle={`${agentName} · ${conversationTitle}`}
            modelLabel={
              currentAgent?.default_model_id ? "智能体默认模型" : overview?.model?.model
                ? `${overview.model.provider} · ${overview.model.model}`
                : "默认模型未配置"
            }
            requestError={pageError}
            messages={messages}
            activity={activity}
            draft={draft}
            busy={busy}
            onSubmit={(event) => void sendMessage(event)}
            onDraftChange={setDraft}
            onCancel={() => void cancelRun()}
          />
        ) : (
          <>
            <header className="topbar">
              <div>
                <small>
                  {page === "overview"
                    ? "星栖 · 本地 Agent"
                    : page === "providers"
                      ? "模型与推理"
                      : page === "channels"
                        ? "OneBot / NapCat"
                        : page === "plugins"
                          ? `${agentName} · MCP 服务与 Skills`
                          : page === "diagnostics"
                              ? "事件、投递与故障"
                              : page === "memory"
                                ? "每日观察与记忆沉淀"
                                : "身份、人格与共同记忆"}
                </small>
                <h1>{titles[page]}</h1>
              </div>
              <div className="header-actions">
                {page === "providers" && (
                  <button
                    className="primary"
                    onClick={() => void addProvider()}
                  >
                    添加 Provider
                  </button>
                )}
                {page === "plugins" && pluginTab === "mcp" && (
                  <button className="primary" onClick={() => void addMcp()}>
                    添加 MCP
                  </button>
                )}
                {page === "plugins" && pluginTab === "skills" && (
                  <button
                    className="primary"
                    onClick={() => void installSkill()}
                  >
                    安装 Skill
                  </button>
                )}
                <button
                  className="quiet"
                  onClick={() =>
                    page === "overview"
                      ? void refreshOverview()
                      : page === "diagnostics"
                        ? void navigate("diagnostics")
                        : void navigate(page)
                  }
                >
                  刷新状态
                </button>
              </div>
            </header>
            {page === "memory" ? (
              <MemoryPage reloadKey={pageRevision} />
            ) : (
              <>
                {pageError ? (
                  <div className="page-content" role="alert">
                    <StateCard
                      title="页面数据读取失败"
                      description={pageError}
                      action={
                        <button
                          className="quiet"
                          onClick={() => void navigate(page)}
                        >
                          重试
                        </button>
                      }
                    />
                  </div>
                ) : (
                  pageBody
                )}
              </>
            )}
          </>
        )}
      </main>
      </AgentScope.Provider>
    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
