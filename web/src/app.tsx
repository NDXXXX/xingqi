import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import { deriveOverview, type ApiResult } from "./overview";
import { errorText, request } from "./api";
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
  const [reminderNotices, setReminderNotices] = useState<Item[]>([]);
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
    async () => setConversations(await request<Item[]>("/api/conversations")),
    [],
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
    refreshConversations,
    onConversationCreated,
    onErrorClear: onChatErrorClear,
    onRequestError: reportPageError,
  });
  useEffect(() => {
    let active = true;
    const seen = new Set(
      (sessionStorage.getItem("zhiyu-seen-reminders") || "")
        .split("|").filter(Boolean),
    );
    const refresh = async () => {
      const rows = await request<Item[]>("/api/reminders/recent");
      if (!active) return;
      const fresh = rows.filter((item) => {
        const key = `${item.id}:${item.fired_at}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      if (fresh.length) {
        sessionStorage.setItem(
          "zhiyu-seen-reminders", Array.from(seen).slice(-100).join("|"),
        );
        setReminderNotices((current) => [...fresh, ...current].slice(0, 5));
      }
    };
    void refresh().catch(() => undefined);
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);
  const openConversation = useCallback(
    async (id: string, title?: string) => {
      closeMobileMenu();
      await cancelRun();
      setActivity("");
      const loadId = ++conversationLoadRef.current;
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
    history.pushState({}, "", "/?page=chat");
  }, [cancelRun, clearMessages, closeMobileMenu]);
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
        target === "overview" ? "/" : target === "plugins"
          ? `/?page=plugins&tab=${pluginTab}` : `/?page=${target}`,
      );
    },
    [busy, cancelRun, closeMobileMenu, pluginTab],
  );

  function selectPluginTab(tab: "mcp" | "skills") {
    setPluginTab(tab);
    setPageError("");
    history.pushState({}, "", `/?page=plugins&tab=${tab}`);
  }

  useEffect(() => {
    void refreshOverview();
    void refreshConversations();
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
      if (id)
        void (async () => {
          await cancelRun();
          const rows = await request<Item[]>(
            `/api/conversations/${encodeURIComponent(id)}/messages`,
          );
          setMessages(
            rows.map((row) => ({
              ...row,
              role: row.role === "user" ? "user" : "assistant",
            })),
          );
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
  );

  const pageBody = (() => {
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
        <AboutEachOtherPage
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
            {conversations.slice(0, 30).map((item) => (
              <button
                key={item.id}
                className={`conversation ${item.id === conversationId ? "active" : ""}`}
                onClick={() => void openConversation(item.id, item.title)}
              >
                {item.title || "未命名会话"}
              </button>
            ))}
            {conversations.length === 0 && (
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
      <main className="main">
        {page === "chat" ? (
          <ChatPage
            conversationTitle={conversationTitle}
            modelLabel={
              overview?.model?.model
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
                          ? "MCP 服务与 Skills"
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
      {reminderNotices.length > 0 && (
        <aside className="reminder-notices" aria-live="polite" aria-label="定时提醒">
          {reminderNotices.map((item) => (
            <div className="reminder-notice" key={`${item.id}:${item.fired_at}`}>
              <strong>星栖提醒</strong>
              <p>{item.content}</p>
              <div>
                <button onClick={() => {
                  setReminderNotices((current) => current.filter((row) => row !== item));
                  void openConversation(item.conversation_id).catch((error) =>
                    setPageError(errorText(error))
                  );
                }}>查看会话</button>
                <button onClick={() =>
                  setReminderNotices((current) => current.filter((row) => row !== item))
                }>关闭</button>
              </div>
            </div>
          ))}
        </aside>
      )}
    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
