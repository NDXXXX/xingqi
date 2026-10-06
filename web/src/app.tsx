import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import { deriveOverview, type ApiResult } from "./overview";
import { errorText, post, request } from "./api";
import { StateCard } from "./components/StateCard";
import { ChatPage } from "./pages/ChatPage";
import { MemoryPage } from "./pages/MemoryPage";
import { useChatSession } from "./hooks/useChatSession";
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
  { id: "providers", icon: "◈", label: "模型服务" },
  { id: "channels", icon: "⌁", label: "QQ 渠道" },
  { id: "mcp", icon: "◇", label: "MCP 服务" },
  { id: "skills", icon: "▧", label: "Skills" },
  { id: "diagnostics", icon: "⌘", label: "运行诊断" },
  { id: "memory", icon: "✳", label: "长期记忆" },
];
const titles: Record<Page, string> = {
  overview: "运行总览",
  chat: "对话",
  providers: "模型服务",
  channels: "QQ 渠道",
  mcp: "MCP 服务",
  skills: "Skills",
  diagnostics: "运行诊断",
  memory: "长期记忆",
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
    const value = new URLSearchParams(location.search).get("page") as Page;
    return nav.some((item) => item.id === value) ? value : "overview";
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
  const conversationLoadRef = useRef(0);
  const dialog = window.zhiyuDialogs;

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
  });
  const openConversation = useCallback(
    async (id: string, title?: string) => {
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
    [cancelRun],
  );
  const startNewChat = useCallback(async () => {
    await cancelRun();
    conversationLoadRef.current += 1;
    setConversationId(null);
    setConversationTitle("新的对话");
    clearMessages();
    setActivity("");
    setPage("chat");
    history.pushState({}, "", "/?page=chat");
  }, [cancelRun, clearMessages]);
  const navigate = useCallback(
    async (target: Page) => {
      if (busy && target !== "chat") await cancelRun();
      setPage(target);
      setPageError("");
      setPageRevision((value) => value + 1);
      history.pushState(
        {},
        "",
        target === "overview" ? "/" : `/?page=${target}`,
      );
    },
    [busy, cancelRun],
  );

  useEffect(() => {
    void refreshOverview();
    void refreshConversations();
    const onPop = () => {
      const params = new URLSearchParams(location.search);
      const target = (params.get("page") as Page) || "overview";
      const id = params.get("conversation");
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
  }, [refreshOverview, refreshConversations, cancelRun, clearMessages]);
  useEffect(() => {
    const id = new URLSearchParams(location.search).get("conversation");
    if (id)
      void openConversation(id).catch((error) =>
        setPageError(errorText(error)),
      );
    // URL synchronization is intentionally triggered only by the initial/deep-linked conversation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function act(action: () => Promise<unknown>, refresh = true) {
    try {
      await action();
      if (refresh) await refreshOverview();
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "操作失败");
    }
  }
  async function addProvider() {
    const values = await dialog.form(
      "添加模型服务",
      "API Key 不会再次显示。",
      [
        {
          name: "name",
          label: "Provider 名称",
          required: true,
          placeholder: "例如 deepseek",
        },
        {
          name: "provider_type",
          label: "类型",
          type: "select",
          value: "deepseek",
          options: ["deepseek", "minimax", "kimi", "openai", "anthropic"].map(
            (value) => ({ value, label: value }),
          ),
        },
        { name: "api_key", label: "API Key", type: "password" },
        { name: "api_key_env", label: "环境变量名" },
        { name: "base_url", label: "Base URL", type: "url" },
      ],
      "保存 Provider",
    );
    if (!values) return;
    if (values.api_key && values.api_key_env) {
      await dialog.alert("API Key 与环境变量只能填写一个。", "配置无效");
      return;
    }
    await act(async () => {
      await request(
        "/api/providers",
        post("POST", {
          ...values,
          api_key: values.api_key || null,
          api_key_env: values.api_key_env || null,
          base_url: values.base_url || null,
        }),
      );
      setPageRevision((value) => value + 1);
    });
  }
  async function addMcp() {
    const values = await dialog.form(
      "添加 MCP Server",
      "新服务默认停用。",
      [
        { name: "name", label: "名称", required: true },
        {
          name: "transport",
          label: "传输方式",
          type: "select",
          value: "stdio",
          options: [
            { value: "stdio", label: "stdio" },
            { value: "streamable_http", label: "Streamable HTTP" },
            { value: "sse", label: "SSE" },
          ],
        },
        { name: "command", label: "命令（stdio）" },
        { name: "args", label: "参数 JSON 数组", value: "[]" },
        { name: "url", label: "远程 URL" },
      ],
      "添加",
    );
    if (!values) return;
    await act(async () => {
      const transport = String(values.transport);
      await request(
        "/api/mcp/servers",
        post("POST", {
          name: values.name,
          transport,
          command: transport === "stdio" ? values.command : null,
          args: JSON.parse(String(values.args || "[]")),
          url: transport === "stdio" ? null : values.url,
          enabled: false,
        }),
      );
      setPageRevision((value) => value + 1);
    });
  }
  async function installSkill() {
    const source = await dialog.prompt(
      "本地目录路径或 HTTPS Git 仓库地址",
      "",
      { title: "安装 Skill", placeholder: "https://github.com/owner/repo" },
    );
    if (!source) return;
    await act(async () => {
      const preview = await request<Item>(
        "/api/skills/preview",
        post("POST", { source }),
      );
      if (
        !(await dialog.confirm(
          `即将安装 ${preview.name}（${preview.files?.length || 0} 个文件）。\n${(preview.warnings || []).join("\n")}`,
          "确认安装",
        ))
      )
        return;
      await request("/api/skills/install", post("POST", { source }));
      setPageRevision((value) => value + 1);
    });
  }

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
    if (page === "mcp")
      return (
        <McpPage
          reloadKey={pageRevision}
          onLoadError={reportPageError}
          act={act}
          addMcp={addMcp}
        />
      );
    if (page === "skills")
      return (
        <SkillsPage
          reloadKey={pageRevision}
          onLoadError={reportPageError}
          act={act}
          installSkill={installSkill}
        />
      );
    if (page === "diagnostics")
      return (
        <DiagnosticsPage
          reloadKey={pageRevision}
          onLoadError={reportPageError}
          act={act}
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
        <div className="brand">
          <span className="brand-mark">知</span>
          <div>
            <strong>知语</strong>
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
                    ? "知语 · 本地 Agent"
                    : page === "providers"
                      ? "模型与推理"
                      : page === "channels"
                        ? "OneBot / NapCat"
                        : page === "mcp"
                          ? "外部工具与上下文"
                          : page === "skills"
                            ? "本地能力扩展"
                            : page === "diagnostics"
                              ? "事件、投递与故障"
                              : "可查看、搜索与纠正"}
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
                {page === "mcp" && (
                  <button className="primary" onClick={() => void addMcp()}>
                    添加 MCP
                  </button>
                )}
                {page === "skills" && (
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
    </div>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
