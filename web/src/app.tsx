import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { createRoot } from "react-dom/client";
import { deriveOverview, type ApiResult } from "./overview";
import { isCurrentRequest } from "./chatState";
import "./app.css";

type Item = Record<string, any>;
type Page =
  | "overview"
  | "chat"
  | "providers"
  | "channels"
  | "mcp"
  | "skills"
  | "diagnostics"
  | "memory";
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
const request = async <T,>(
  url: string,
  options: RequestInit = {},
): Promise<T> => {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
};
const post = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});
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
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
const stamp = (value: string) =>
  value ? new Date(value).toLocaleString() : "";
const parseList = (value: string): Item[] => {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
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
  const [messages, setMessages] = useState<Item[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState("");
  const [providers, setProviders] = useState<Item[]>([]);
  const [qq, setQq] = useState<Item | null>(null);
  const [channels, setChannels] = useState<Item[]>([]);
  const [groups, setGroups] = useState<Item[]>([]);
  const [mcps, setMcps] = useState<Item[]>([]);
  const [skills, setSkills] = useState<Item[]>([]);
  const [trash, setTrash] = useState<Item[]>([]);
  const [events, setEvents] = useState<Item[]>([]);
  const [deliveries, setDeliveries] = useState<Item[]>([]);
  const [memories, setMemories] = useState<Item[]>([]);
  const [consolidationRuns, setConsolidationRuns] = useState<Item[]>([]);
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryTier, setMemoryTier] = useState("");
  const [pageLoading, setPageLoading] = useState(false);
  const [pageRevision, setPageRevision] = useState(0);
  const [pageError, setPageError] = useState("");
  const streamRef = useRef<{
    controller: AbortController;
    runId: string | null;
    conversationId: string | null;
  } | null>(null);
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
  const cancelRun = useCallback(async () => {
    const current = streamRef.current;
    if (!current) return;
    current.controller.abort();
    if (current.runId)
      await request(
        `/api/runs/${encodeURIComponent(current.runId)}/cancel`,
        post("POST"),
      ).catch(() => undefined);
    setMessages((rows) =>
      rows.map((item, index) =>
        index === rows.length - 1 && item.pending
          ? { ...item, pending: false, cancelled: true }
          : item,
      ),
    );
    streamRef.current = null;
    setBusy(false);
    setActivity("已停止，已生成内容已保留");
  }, []);
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
    setMessages([]);
    setActivity("");
    setPage("chat");
    history.pushState({}, "", "/?page=chat");
  }, [cancelRun]);
  const navigate = useCallback(
    async (target: Page) => {
      if (streamRef.current && target !== "chat") await cancelRun();
      setPage(target);
      setPageError("");
      setPageRevision((value) => value + 1);
      history.pushState(
        {},
        "",
        target === "overview" ? "/" : `/?page=${target}`,
      );
    },
    [cancelRun],
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
        setMessages([]);
        setConversationTitle("新的对话");
      }
    };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, [refreshOverview, refreshConversations, cancelRun]);
  useEffect(() => {
    const id = new URLSearchParams(location.search).get("conversation");
    if (id)
      void openConversation(id).catch((error) =>
        setPageError(errorText(error)),
      );
    // URL synchronization is intentionally triggered only by the initial/deep-linked conversation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    let alive = true;
    async function load() {
      setPageLoading(true);
      setPageError("");
      try {
        if (page === "providers")
          setProviders(
            await request<Item[]>("/api/providers").then(async (items) =>
              Promise.all(
                items.map(async (item) => ({
                  ...item,
                  detail: await request<Item>(
                    `/api/providers/${encodeURIComponent(item.name)}`,
                  ),
                })),
              ),
            ),
          );
        if (page === "channels") {
          const [config, list, groupList] = await Promise.all([
            request<Item>("/api/qq/config"),
            request<Item[]>("/api/channels"),
            request<Item[]>("/api/qq/groups"),
          ]);
          setQq(config);
          setChannels(list);
          setGroups(groupList);
        }
        if (page === "mcp") setMcps(await request<Item[]>("/api/mcp/servers"));
        if (page === "skills") {
          const [list, old] = await Promise.all([
            request<Item[]>("/api/skills"),
            request<Item[]>("/api/skills/trash"),
          ]);
          setSkills(list);
          setTrash(old);
        }
        if (page === "diagnostics") {
          const [inbound, outbound] = await Promise.all([
            request<Item[]>("/api/channel-events?limit=100"),
            request<Item[]>("/api/channel-deliveries?limit=100"),
          ]);
          setEvents(inbound);
          setDeliveries(outbound);
        }
        if (page === "memory") {
          const params = new URLSearchParams();
          if (memoryQuery) params.set("query", memoryQuery);
          if (memoryTier) params.set("tier", memoryTier);
          const [items, runs] = await Promise.all([
            request<Item[]>(`/api/memories?${params}`),
            request<Item[]>("/api/memory-consolidation-runs?limit=5"),
          ]);
          setMemories(items);
          setConsolidationRuns(runs);
        }
      } catch (error) {
        if (alive) setPageError(errorText(error));
      } finally {
        if (alive) setPageLoading(false);
      }
    }
    if (page !== "overview" && page !== "chat") void load();
    return () => {
      alive = false;
    };
  }, [page, memoryQuery, memoryTier, pageRevision]);

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    const requestId = conversationId;
    const controller = new AbortController();
    const run = {
      controller,
      runId: null as string | null,
      conversationId: requestId,
    };
    streamRef.current = run;
    setBusy(true);
    setDraft("");
    setPageError("");
    setMessages((current) => [
      ...current,
      { role: "user", content: text },
      { role: "assistant", content: "", pending: true },
    ]);
    setActivity("正在思考…");
    const updateAssistant = (change: (previous: Item) => Item) =>
      setMessages((current) => {
        if (!isCurrentRequest(streamRef.current, run)) return current;
        const index = current.length - 1;
        return current.map((item, i) => (i === index ? change(item) : item));
      });
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: requestId }),
        signal: controller.signal,
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
          const line = block
            .split("\n")
            .find((part) => part.startsWith("data: "));
          if (!line) continue;
          const message = JSON.parse(line.slice(6));
          if (!isCurrentRequest(streamRef.current, run)) continue;
          if (message.type === "run") {
            run.runId = message.run_id || null;
            if (requestId === null) {
              setConversationId(message.conversation_id);
              setConversationTitle("新对话");
              history.replaceState(
                {},
                "",
                `/?page=chat&conversation=${encodeURIComponent(message.conversation_id)}`,
              );
            }
          }
          if (message.type === "chunk")
            updateAssistant((item) => ({
              ...item,
              content: `${item.content || ""}${message.text}`,
            }));
          if (message.type === "tool" || message.type === "step")
            setActivity(
              message.type === "tool"
                ? `工具 · ${message.name} · ${message.status}`
                : message.name,
            );
          if (message.type === "error") throw new Error(message.error);
          if (message.type === "done")
            updateAssistant((item) => ({
              ...item,
              content: item.content || message.response,
              pending: false,
            }));
        }
        if (done) break;
      }
      if (isCurrentRequest(streamRef.current, run)) {
        setActivity("");
        await refreshConversations();
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        updateAssistant((item) => ({
          ...item,
          pending: false,
          error: errorText(error),
          content: item.content || "",
        }));
        setActivity("");
      }
    } finally {
      if (isCurrentRequest(streamRef.current, run)) {
        streamRef.current = null;
        setBusy(false);
      }
    }
  }

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
      setProviders(
        await request<Item[]>("/api/providers").then(async (items) =>
          Promise.all(
            items.map(async (item) => ({
              ...item,
              detail: await request<Item>(
                `/api/providers/${encodeURIComponent(item.name)}`,
              ),
            })),
          ),
        ),
      );
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
      setMcps(await request<Item[]>("/api/mcp/servers"));
    });
  }
  async function loadProvidersIntoState() {
    setProviders(
      await request<Item[]>("/api/providers").then(async (items) =>
        Promise.all(
          items.map(async (item) => ({
            ...item,
            detail: await request<Item>(
              `/api/providers/${encodeURIComponent(item.name)}`,
            ),
          })),
        ),
      ),
    );
  }
  async function editModel(provider: string, model: Item) {
    const values = await dialog.form(
      "模型能力",
      "按字段编辑模型，无需修改 JSON。",
      [
        {
          name: "model_name",
          label: "模型标识",
          value: model.model_name,
          required: true,
        },
        {
          name: "display_name",
          label: "显示名称",
          value: model.display_name || model.model_name,
        },
        {
          name: "enabled",
          label: "启用",
          type: "checkbox",
          value: model.enabled,
        },
        {
          name: "supports_tools",
          label: "支持工具",
          type: "checkbox",
          value: model.supports_tools,
        },
        {
          name: "supports_streaming",
          label: "支持流式",
          type: "checkbox",
          value: model.supports_streaming,
        },
        {
          name: "supports_vision",
          label: "支持视觉",
          type: "checkbox",
          value: model.supports_vision,
        },
        {
          name: "context_window",
          label: "上下文窗口 Token",
          type: "number",
          value: model.context_window || "",
        },
        {
          name: "max_output_tokens",
          label: "最大输出 Token",
          type: "number",
          value: model.max_output_tokens || "",
        },
      ],
      "保存模型",
    );
    if (!values) return;
    await act(async () => {
      await request(
        `/api/providers/${encodeURIComponent(provider)}/models/${encodeURIComponent(model.id)}`,
        post("PUT", {
          ...values,
          context_window: values.context_window
            ? Number(values.context_window)
            : null,
          max_output_tokens: values.max_output_tokens
            ? Number(values.max_output_tokens)
            : null,
        }),
      );
      await loadProvidersIntoState();
    }, false);
  }
  async function configureFallback(name: string, current: string[]) {
    const raw = await dialog.prompt(
      "按优先顺序输入备用 Provider 名称，用逗号分隔。不能引用自身或重复。",
      current.join(", "),
      { title: "配置故障切换" },
    );
    if (raw === null) return;
    const values = raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (values.includes(name) || new Set(values).size !== values.length) {
      await dialog.alert("备用 Provider 不能引用自身或重复。", "配置无效");
      return;
    }
    await act(async () => {
      await request(
        `/api/providers/${encodeURIComponent(name)}/fallbacks`,
        post("PUT", { providers: values }),
      );
      await loadProvidersIntoState();
    }, false);
  }
  async function configureMcpAccess(name: string) {
    const found = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}/test`,
      post("POST"),
    );
    const detail = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}`,
    );
    const fields = [
      ...(found.tools || []).map((tool: string) => ({
        name: `tool:${tool}`,
        label: `工具 · ${tool}`,
        type: "checkbox",
        value: (detail.tool_allowlist || []).includes(tool),
      })),
      ...(found.resources || []).map((resource: Item) => ({
        name: `resource:${resource.uri || resource}`,
        label: `Resource · ${resource.uri || resource}`,
        type: "checkbox",
        value: (detail.resource_allowlist || []).includes(
          resource.uri || resource,
        ),
      })),
      ...(found.prompts || []).map((prompt: Item) => ({
        name: `prompt:${prompt.name || prompt}`,
        label: `Prompt · ${prompt.name || prompt}`,
        type: "checkbox",
        value: (detail.prompt_allowlist || []).includes(prompt.name || prompt),
      })),
    ];
    if (!fields.length) {
      await dialog.alert(
        "此服务没有发现可授权的 Tools、Resources 或 Prompts。",
        "没有可配置能力",
      );
      return;
    }
    const selected = await dialog.form(
      "授权 MCP 能力",
      "新发现的能力默认关闭；仅勾选你信任并需要的项目。",
      fields,
      "保存授权",
    );
    if (!selected) return;
    await request(
      `/api/mcp/servers/${encodeURIComponent(name)}/tools/allowlist`,
      post("PUT", {
        values: fields
          .filter(
            (field) =>
              field.name.startsWith("tool:") && selected[field.name] === true,
          )
          .map((field) => field.name.slice(5)),
      }),
    );
    await request(
      `/api/mcp/servers/${encodeURIComponent(name)}/resource/allowlist`,
      post("PUT", {
        values: fields
          .filter(
            (field) =>
              field.name.startsWith("resource:") &&
              selected[field.name] === true,
          )
          .map((field) => field.name.slice(9)),
      }),
    );
    await request(
      `/api/mcp/servers/${encodeURIComponent(name)}/prompt/allowlist`,
      post("PUT", {
        values: fields
          .filter(
            (field) =>
              field.name.startsWith("prompt:") && selected[field.name] === true,
          )
          .map((field) => field.name.slice(7)),
      }),
    );
    setMcps(await request<Item[]>("/api/mcp/servers"));
  }
  async function configureMcpSecrets(item: Item) {
    const name = item.name;
    const detail = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}`,
    );
    let removed = false;
    if (
      detail.secret_names?.length &&
      (await dialog.confirm(
        `删除已保存的密钥引用？\n${detail.secret_names.join("\n")}`,
        "删除 MCP 凭据",
      ))
    ) {
      const ref = await dialog.prompt(
        "输入要删除的完整引用名称",
        detail.secret_names[0],
        { title: "删除已保存 Secret" },
      );
      if (ref === null) return;
      if (ref?.startsWith("env:"))
        await request(
          `/api/mcp/servers/${encodeURIComponent(name)}/env`,
          post("PUT", { key: ref.slice(4), value: null, secret: true }),
        );
      if (ref?.startsWith("env:")) removed = true;
      if (ref?.startsWith("header:"))
        await request(
          `/api/mcp/servers/${encodeURIComponent(name)}/header-secret`,
          post("PUT", { name: ref.slice(7), value: null }),
        );
      if (ref?.startsWith("header:")) removed = true;
    }
    if (removed) {
      setMcps(await request<Item[]>("/api/mcp/servers"));
      return;
    }
    if (item.transport === "stdio") {
      const ordinary = await dialog.prompt(
        "普通环境变量 KEY=VALUE，删除用 -KEY",
        "",
        { title: `环境变量 · ${name}` },
      );
      if (ordinary) {
        const remove = ordinary.startsWith("-");
        const split = ordinary.indexOf("=");
        const key = remove ? ordinary.slice(1) : ordinary.slice(0, split);
        if (!key || (!remove && split < 1))
          throw new Error("格式应为 KEY=VALUE 或 -KEY");
        await request(
          `/api/mcp/servers/${encodeURIComponent(name)}/env`,
          post("PUT", {
            key,
            value: remove ? null : ordinary.slice(split + 1),
          }),
        );
      }
      const secret = await dialog.form(
        "Secret 环境变量",
        "密钥仅本次输入并存入本机密钥存储。",
        [
          { name: "key", label: "变量名", required: true },
          {
            name: "value",
            label: "Secret 值",
            type: "password",
            required: true,
          },
        ],
      );
      if (secret)
        await request(
          `/api/mcp/servers/${encodeURIComponent(name)}/env`,
          post("PUT", { key: secret.key, value: secret.value, secret: true }),
        );
    } else {
      const values = await dialog.form(
        "HTTP Header Secret",
        "已保存的 Secret 不会回显；留空不能覆盖已保存的值。",
        [
          {
            name: "header",
            label: "Header 名称",
            required: true,
            placeholder: "Authorization",
          },
          {
            name: "value",
            label: "Secret 值",
            type: "password",
            required: true,
          },
        ],
      );
      if (values)
        await request(
          `/api/mcp/servers/${encodeURIComponent(name)}/header-secret`,
          post("PUT", { name: values.header, value: values.value }),
        );
    }
    if (detail.secret_names?.length)
      window.zhiyuDialogs.notify(
        `已保存的密钥引用：${detail.secret_names.join("、")}`,
      );
    setMcps(await request<Item[]>("/api/mcp/servers"));
  }
  async function editMcpConnection(item: Item) {
    const detail = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(item.name)}`,
    );
    const values = await dialog.form(
      `连接配置 · ${item.name}`,
      "修改连接方式会按新配置重载该 Server。",
      [
        {
          name: "transport",
          label: "传输方式",
          type: "select",
          value: detail.transport,
          options: [
            { value: "stdio", label: "stdio" },
            { value: "streamable_http", label: "Streamable HTTP" },
            { value: "sse", label: "SSE" },
          ],
        },
        {
          name: "command",
          label: "启动命令",
          value: detail.command || "",
          dependsOn: { name: "transport", value: "stdio" },
        },
        {
          name: "args",
          label: "参数 JSON 数组",
          value: JSON.stringify(detail.args || []),
          dependsOn: { name: "transport", value: "stdio" },
        },
        {
          name: "url",
          label: "远程服务 URL",
          value: detail.url || "",
          dependsOn: { name: "transport", value: "streamable_http" },
        },
        {
          name: "sse_url",
          label: "SSE URL",
          value: detail.url || "",
          dependsOn: { name: "transport", value: "sse" },
        },
      ],
      "保存连接",
    );
    if (!values) return;
    const transport = String(values.transport);
    const args = JSON.parse(String(values.args || "[]"));
    if (!Array.isArray(args) || args.some((value) => typeof value !== "string"))
      throw new Error("参数必须是字符串数组。");
    await request(
      "/api/mcp/servers",
      post("POST", {
        name: item.name,
        transport,
        command: transport === "stdio" ? values.command : null,
        args: transport === "stdio" ? args : [],
        url:
          transport === "stdio"
            ? null
            : transport === "sse"
              ? values.sse_url
              : values.url,
        enabled: detail.enabled,
      }),
    );
    setMcps(await request<Item[]>("/api/mcp/servers"));
  }
  async function readMcpResource(name: string) {
    const found = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}/test`,
      post("POST"),
    );
    const detail = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}`,
    );
    const available = (found.resources || [])
      .map((item: Item) => item.uri || item)
      .filter((uri: string) => (detail.resource_allowlist || []).includes(uri));
    const uri = await dialog.prompt(
      `已授权 Resource：${available.join(", ") || "无"}`,
      available[0] || "",
      { title: "读取 MCP Resource" },
    );
    if (!uri) return;
    const result = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}/resources/read`,
      post("POST", { uri }),
    );
    await dialog.alert(
      `外部内容 · 不可信文本${result.truncated ? "（已截断）" : ""}\n\n${result.content.slice(0, 5000)}`,
      "Resource 内容",
    );
  }
  async function renderMcpPrompt(name: string) {
    const found = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}/test`,
      post("POST"),
    );
    const detail = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}`,
    );
    const available = (found.prompts || [])
      .map((item: Item) => item.name || item)
      .filter((prompt: string) =>
        (detail.prompt_allowlist || []).includes(prompt),
      );
    const prompt = await dialog.prompt(
      `已授权 Prompt：${available.join(", ") || "无"}`,
      available[0] || "",
      { title: "运行 MCP Prompt" },
    );
    if (!prompt) return;
    const raw = await dialog.prompt("Prompt 参数 JSON", "{}", {
      title: "填写 Prompt 参数",
    });
    if (raw === null) return;
    const result = await request<Item>(
      `/api/mcp/servers/${encodeURIComponent(name)}/prompts/render`,
      post("POST", { prompt, arguments: JSON.parse(raw) }),
    );
    await dialog.alert(
      `外部内容 · 不可信文本${result.truncated ? "（已截断）" : ""}\n\n${result.content.slice(0, 5000)}`,
      "Prompt 结果",
    );
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
      setSkills(await request<Item[]>("/api/skills"));
      setTrash(await request<Item[]>("/api/skills/trash"));
    });
  }

  const renderOverview = () => {
    const data = overview;
    if (overviewLoading && !data)
      return (
        <div className="page-content">
          <StateCard title="正在读取运行状态…" />
        </div>
      );
    if (!data)
      return (
        <div className="page-content">
          <StateCard
            title="运行状态不可用"
            action={
              <button className="quiet" onClick={() => void refreshOverview()}>
                重试
              </button>
            }
          />
        </div>
      );
    const statusClass = data.complete
      ? data.problems.length
        ? "warn"
        : "good"
      : "warn";
    const healthRows = [
      {
        name: "知语运行时",
        detail: data.health ? "Web、Agent 与后台任务" : "接口读取失败",
        status: data.health
          ? data.health.started
            ? data.health.degraded
              ? "降级"
              : "运行中"
            : "未启动"
          : "未知",
        good: Boolean(data.health?.started && !data.health?.degraded),
        neutral: !data.health,
      },
      {
        name: "QQ / OneBot",
        detail:
          data.qq?.last_error ||
          data.qq?.ws_url ||
          (data.qqConfigured ? "已配置，等待连接" : "未配置或状态接口失败"),
        status: data.qq
          ? data.qq.status
          : !data.channels || !data.qqConfig.ok
            ? "未知"
            : data.qqConfigured
              ? "未连接"
              : "未配置",
        good: data.qq?.status === "connected",
        neutral:
          !data.qq &&
          Boolean(data.channels) &&
          data.qqConfig.ok &&
          !data.qqConfigured,
      },
      {
        name: "MCP",
        detail: !data.mcp
          ? "接口读取失败"
          : data.enabledMcp.length
            ? `${data.enabledMcp.filter((item) => item.status === "ready").length}/${data.enabledMcp.length} 个启用服务就绪`
            : "未启用（可选）",
        status: !data.mcp
          ? "未知"
          : data.enabledMcp.length
            ? data.enabledMcp.every((item) => item.status === "ready")
              ? "正常"
              : "需要检查"
            : "未启用",
        good: Boolean(
          data.mcp &&
          (!data.enabledMcp.length ||
            data.enabledMcp.every((item) => item.status === "ready")),
        ),
        neutral: Boolean(data.mcp && !data.enabledMcp.length),
      },
      {
        name: "Skills",
        detail: !data.skills
          ? "接口读取失败"
          : data.enabledSkills.length
            ? `${data.enabledSkills.filter((item) => item.available).length}/${data.enabledSkills.length} 个启用项可用`
            : "未启用（可选）",
        status: !data.skills
          ? "未知"
          : data.enabledSkills.some((item) => !item.available)
            ? "缺少依赖"
            : "正常",
        good: Boolean(
          data.skills && !data.enabledSkills.some((item) => !item.available),
        ),
        neutral: Boolean(data.skills && !data.enabledSkills.length),
      },
      {
        name: "记忆任务",
        detail: data.health
          ? `${data.health.memory_jobs?.completed ?? 0} 项已完成`
          : "运行时状态未知",
        status: data.health?.started
          ? "后台运行"
          : data.health
            ? "停止"
            : "未知",
        good: Boolean(data.health?.started),
        neutral: !data.health,
      },
    ];
    const runtimeText = data.health
      ? data.health.started
        ? data.health.degraded
          ? "部分降级"
          : "运行中"
        : "未启动"
      : "未知";
    const modelText = data.model?.model
      ? `${data.model.provider} · ${data.model.model}`
      : data.defaultModel
        ? "未配置"
        : "接口不可用";
    return (
      <div className="page-content">
        <div className="dashboard-top">
          <div className="dashboard-side">
            <article className="identity-card panel">
              <div className="identity-mark">知</div>
              <div>
                <strong>知语</strong>
                <small>Personal Agent</small>
              </div>
              <span className={`status-pill ${statusClass}`}>
                {overviewLoading ? "刷新中" : data.label}
              </span>
            </article>
            <article className="system-card panel">
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">SYSTEM</span>
                  <h2>系统信息</h2>
                </div>
              </div>
              <div className="system-lines">
                <div>
                  <span>运行状态</span>
                  <strong>{runtimeText}</strong>
                </div>
                <div>
                  <span>默认模型</span>
                  <strong title={modelText}>{modelText}</strong>
                </div>
                <div>
                  <span>QQ 主人</span>
                  <strong>
                    {data.qqConfig.ok
                      ? data.qqConfig.value?.owner_user_id || "未设置"
                      : "接口不可用"}
                  </strong>
                </div>
                <div>
                  <span>运行方式</span>
                  <strong>本机 · 单用户</strong>
                </div>
              </div>
            </article>
          </div>
          <article className="health-panel panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">SERVICE HEALTH</span>
                <h2>服务状态</h2>
              </div>
              <button
                className="text-button"
                onClick={() => void navigate("diagnostics")}
              >
                打开诊断 →
              </button>
            </div>
            <div className="health-list">
              {healthRows.map((row) => (
                <div className="health-row" key={row.name}>
                  <span
                    className={`health-indicator ${row.good ? "good" : row.neutral ? "neutral" : "warn"}`}
                  ></span>
                  <div className="health-copy">
                    <strong>{row.name}</strong>
                    <small>{row.detail}</small>
                  </div>
                  <span className="health-state">{row.status}</span>
                </div>
              ))}
            </div>
            {data.errors.length > 0 && (
              <p className="overview-warning">
                检查不完整：{data.errors.join("、")}
              </p>
            )}
            <div className="health-footnote">
              渠道事件统计仅覆盖最近 50 条记录，不代表完整队列。
            </div>
          </article>
        </div>
        <div className="counter-strip">
          <article className="counter-card counter-main">
            <strong>
              {data.providers ? data.enabledProviders.length : "未知"}
            </strong>
            <span>可用模型服务</span>
          </article>
          <article className="counter-card">
            <strong>
              {data.channels
                ? data.qq
                  ? data.qq.status === "connected"
                    ? "已连接"
                    : data.qq.status
                  : "未配置"
                : "未知"}
            </strong>
            <span>QQ 渠道</span>
          </article>
          <article className="counter-card">
            <strong>
              {data.mcp
                ? `${data.enabledMcp.filter((item) => item.status === "ready").length}/${data.enabledMcp.length}`
                : "未知"}
            </strong>
            <span>启用 MCP</span>
          </article>
          <article className="counter-card">
            <strong>
              {data.skills
                ? `${data.enabledSkills.filter((item) => item.available).length}/${data.enabledSkills.length}`
                : "未知"}
            </strong>
            <span>启用 Skills</span>
          </article>
          <article className="counter-card">
            <strong>{data.pending === null ? "未知" : data.pending}</strong>
            <span>待处理 · 最近 50 条</span>
          </article>
        </div>
        <article className="activity-panel panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">RECENT ACTIVITY</span>
              <h2>最近运行</h2>
            </div>
            <button
              className="text-button"
              onClick={() => void navigate("diagnostics")}
            >
              查看全部 →
            </button>
          </div>
          <div className="activity-layout">
            <div className="activity-callout">
              <span className="quote-mark">“</span>
              <p>
                {data.events
                  ? data.failed
                    ? `最近 50 条记录中有 ${data.failed} 条失败。`
                    : data.pending
                      ? `${data.pending} 条事件尚在处理中。`
                      : "最近 50 条渠道事件均已处理。"
                  : "事件状态不可用"}
              </p>
              <small>知语 · 本地运行概览</small>
            </div>
            <div className="simple-list">
              {data.events ? (
                data.events.slice(0, 5).map((item, index) => (
                  <div className="list-row" key={item.id || index}>
                    <span className={`status-dot ${item.status}`}></span>
                    <span className="row-main">{item.status}</span>
                    <small>{stamp(item.received_at)}</small>
                  </div>
                ))
              ) : (
                <p className="muted">读取失败，无法展示渠道事件</p>
              )}
              {data.events?.length === 0 && (
                <p className="muted">暂无渠道事件</p>
              )}
            </div>
          </div>
        </article>
      </div>
    );
  };

  const renderProviders = () => (
    <div className="page-content">
      <div className="notice">
        API Key 会通过本机密钥存储保存；页面不会回显已保存密钥。
      </div>
      {providers.length ? (
        <div className="manage-list">
          {providers.map((item) => (
            <article className="manage-card" key={item.name}>
              <div className="manage-card-head">
                <div>
                  <span className="eyebrow">{item.provider_type}</span>
                  <h2>{item.name}</h2>
                </div>
                <span
                  className={`status-pill ${item.enabled && item.configured ? "good" : "muted-pill"}`}
                >
                  {item.enabled
                    ? item.configured
                      ? "可用"
                      : "未配置密钥"
                    : "已停用"}
                </span>
              </div>
              <p>
                {item.detail?.base_url || "默认 Base URL"} ·{" "}
                {item.detail?.api_key_set ? "密钥已保存" : "未配置密钥"}
              </p>
              <div className="simple-list">
                {(item.detail?.models || []).map((model: Item) => (
                  <div className="list-row" key={model.id}>
                    <span className="row-main">
                      {model.display_name}
                      <small>
                        {" "}
                        · {model.model_name} · {model.enabled ? "启用" : "停用"}{" "}
                        · 工具 {model.supports_tools ? "✓" : "—"} · 流式{" "}
                        {model.supports_streaming ? "✓" : "—"} · 视觉{" "}
                        {model.supports_vision ? "✓" : "—"}
                      </small>
                    </span>
                    <button
                      className="quiet"
                      onClick={() => void editModel(item.name, model)}
                    >
                      编辑
                    </button>
                    <button
                      className="quiet"
                      onClick={() =>
                        void act(async () => {
                          await request(
                            `/api/providers/${encodeURIComponent(item.name)}/models/${encodeURIComponent(model.id)}`,
                            post("PUT", { ...model, enabled: !model.enabled }),
                          );
                          setProviders(
                            await request<Item[]>("/api/providers").then(
                              async (rows) =>
                                Promise.all(
                                  rows.map(async (row) => ({
                                    ...row,
                                    detail: await request<Item>(
                                      `/api/providers/${encodeURIComponent(row.name)}`,
                                    ),
                                  })),
                                ),
                            ),
                          );
                        }, false)
                      }
                    >
                      {model.enabled ? "停用模型" : "启用模型"}
                    </button>
                    <button
                      className="danger-button"
                      onClick={() =>
                        void act(async () => {
                          if (
                            !(await dialog.confirm(
                              "删除该模型配置？若它是默认模型会同时清除默认选择。",
                            ))
                          )
                            return;
                          await request(
                            `/api/providers/${encodeURIComponent(item.name)}/models/${encodeURIComponent(model.id)}`,
                            post("DELETE"),
                          );
                          setProviders(
                            await request<Item[]>("/api/providers").then(
                              async (rows) =>
                                Promise.all(
                                  rows.map(async (row) => ({
                                    ...row,
                                    detail: await request<Item>(
                                      `/api/providers/${encodeURIComponent(row.name)}`,
                                    ),
                                  })),
                                ),
                            ),
                          );
                        })
                      }
                    >
                      删除
                    </button>
                  </div>
                ))}
              </div>
              <div className="card-actions">
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      const model_name = await dialog.prompt("模型标识", "", {
                        title: "添加模型",
                      });
                      if (!model_name) return;
                      await request(
                        `/api/providers/${encodeURIComponent(item.name)}/models`,
                        post("POST", { model_name, display_name: model_name }),
                      );
                      setProviders(
                        await request<Item[]>("/api/providers").then(
                          async (rows) =>
                            Promise.all(
                              rows.map(async (row) => ({
                                ...row,
                                detail: await request<Item>(
                                  `/api/providers/${encodeURIComponent(row.name)}`,
                                ),
                              })),
                            ),
                        ),
                      );
                    }, false)
                  }
                >
                  添加模型
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      const model = await dialog.prompt(
                        `默认模型：${item.models?.join(", ") || ""}`,
                        item.models?.[0] || "",
                        { title: "设置默认模型" },
                      );
                      if (model)
                        await request(
                          "/api/providers/default",
                          post("PUT", { provider: item.name, model }),
                        );
                    })
                  }
                >
                  设为默认
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      const result = await request<Item>(
                        `/api/providers/${encodeURIComponent(item.name)}/test`,
                        post("POST", {}),
                      );
                      window.zhiyuDialogs.notify(
                        `连接成功：${result.response}`,
                      );
                    }, false)
                  }
                >
                  测试连接
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      const detail = item.detail;
                      const values = await dialog.form(
                        "编辑连接配置",
                        "密钥留空表示不替换。",
                        [
                          {
                            name: "base_url",
                            label: "Base URL",
                            value: detail.base_url || "",
                          },
                          {
                            name: "api_key",
                            label: "替换 API Key",
                            type: "password",
                          },
                          {
                            name: "api_key_env",
                            label: "API Key 环境变量名",
                            value: detail.api_key_env || "",
                          },
                          {
                            name: "clear_api_key",
                            label: "清除已保存密钥或环境变量引用",
                            type: "checkbox",
                            value: false,
                          },
                        ],
                      );
                      if (!values) return;
                      if (values.api_key && values.api_key_env)
                        throw new Error("API Key 与环境变量只能填写一个。");
                      await request(
                        `/api/providers/${encodeURIComponent(item.name)}`,
                        post("PUT", {
                          base_url: values.base_url || null,
                          api_key: values.api_key || null,
                          api_key_env: values.api_key_env || null,
                          clear_api_key: values.clear_api_key === true,
                          enabled: item.enabled,
                        }),
                      );
                      setProviders(
                        await request<Item[]>("/api/providers").then(
                          async (rows) =>
                            Promise.all(
                              rows.map(async (row) => ({
                                ...row,
                                detail: await request<Item>(
                                  `/api/providers/${encodeURIComponent(row.name)}`,
                                ),
                              })),
                            ),
                        ),
                      );
                    })
                  }
                >
                  连接配置
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void configureFallback(
                      item.name,
                      item.detail?.fallbacks || [],
                    )
                  }
                >
                  故障切换
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      await request(
                        `/api/providers/${encodeURIComponent(item.name)}`,
                        post("PUT", { enabled: !item.enabled }),
                      );
                      setProviders(
                        await request<Item[]>("/api/providers").then(
                          async (rows) =>
                            Promise.all(
                              rows.map(async (row) => ({
                                ...row,
                                detail: await request<Item>(
                                  `/api/providers/${encodeURIComponent(row.name)}`,
                                ),
                              })),
                            ),
                        ),
                      );
                    })
                  }
                >
                  {item.enabled ? "停用" : "启用"}
                </button>
                <button
                  className="danger-button"
                  onClick={() =>
                    void act(async () => {
                      if (
                        !(await dialog.confirm(
                          `删除 Provider「${item.name}」及其模型配置？`,
                          "删除 Provider",
                        ))
                      )
                        return;
                      await request(
                        `/api/providers/${encodeURIComponent(item.name)}`,
                        post("DELETE"),
                      );
                      setProviders(
                        await request<Item[]>("/api/providers").then(
                          async (rows) =>
                            Promise.all(
                              rows.map(async (row) => ({
                                ...row,
                                detail: await request<Item>(
                                  `/api/providers/${encodeURIComponent(row.name)}`,
                                ),
                              })),
                            ),
                        ),
                      );
                    })
                  }
                >
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        !pageLoading && (
          <StateCard
            title="还没有模型服务"
            description="添加 Provider 后即可开始对话。"
            action={
              <button className="primary" onClick={() => void addProvider()}>
                添加 Provider
              </button>
            }
          />
        )
      )}
    </div>
  );

  const renderChannels = () => (
    <div className="page-content">
      <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">CONNECTION STATUS</span>
            <h2>NapCat / OneBot</h2>
          </div>
          <span
            className={`status-pill ${channels.find((item) => item.channel === "qq")?.status === "connected" ? "good" : "warn"}`}
          >
            {channels.find((item) => item.channel === "qq")?.status || "未连接"}
          </span>
        </div>
        <p>
          {channels.find((item) => item.channel === "qq")?.last_error ||
            channels.find((item) => item.channel === "qq")?.ws_url ||
            "尚未配置连接"}
        </p>
      </article>
      <form
        className="panel form-panel"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void act(async () => {
            await request(
              "/api/qq/config",
              post("PUT", {
                endpoint: form.get("endpoint"),
                owner_user_id: form.get("owner") || null,
                token: form.get("token") || null,
              }),
            );
            setQq(await request<Item>("/api/qq/config"));
          });
        }}
      >
        <div className="panel-heading">
          <div>
            <span className="eyebrow">CONNECTION</span>
            <h2>连接配置</h2>
          </div>
        </div>
        <label>
          NapCat 反向 WebSocket 地址
          <input
            name="endpoint"
            required
            defaultValue={qq?.endpoint || "ws://127.0.0.1:6199/ws"}
          />
        </label>
        <label>
          主人 QQ 号
          <input
            name="owner"
            inputMode="numeric"
            defaultValue={qq?.owner_user_id || ""}
          />
        </label>
        <label>
          Access Token
          <input
            name="token"
            type="password"
            autoComplete="new-password"
            placeholder={
              qq?.token_readable ? "已保存；留空保持不变" : "留空则不设置"
            }
          />
        </label>
        <p className="form-hint">Token 保存在本机密钥存储，不会回显。</p>
        <div className="button-row">
          <button className="primary">保存配置</button>
          <button
            type="button"
            className="quiet"
            onClick={() =>
              void act(async () => {
                await request("/api/qq/start", post("POST"));
                setChannels(await request<Item[]>("/api/channels"));
              })
            }
          >
            启动连接
          </button>
          <button
            type="button"
            className="quiet"
            onClick={() =>
              void act(async () => {
                await request("/api/qq/stop", post("POST"));
                setChannels(await request<Item[]>("/api/channels"));
              })
            }
          >
            停止
          </button>
        </div>
      </form>
      <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">GROUP ACCESS</span>
            <h2>群聊白名单</h2>
          </div>
        </div>
        <form
          className="inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const groupId = String(form.get("group") || "");
            void act(async () => {
              await request(
                `/api/qq/groups/${encodeURIComponent(groupId)}`,
                post("PUT", {
                  enabled: true,
                  require_mention: form.get("mention") === "on",
                }),
              );
              setGroups(await request<Item[]>("/api/qq/groups"));
            });
          }}
        >
          <input name="group" placeholder="QQ群号" required />
          <label className="check">
            <input name="mention" type="checkbox" defaultChecked />
            必须 @ 知语
          </label>
          <button className="quiet">允许此群</button>
        </form>
        <div className="simple-list">
          {groups.map((group) => (
            <div className="list-row" key={group.group_id}>
              <span className="row-main">{group.group_id}</span>
              <small>
                {group.enabled ? "已允许" : "已禁用"} ·{" "}
                {group.require_mention ? "需 @" : "无需 @"}
              </small>
              <button
                className="text-button"
                onClick={() =>
                  void act(async () => {
                    await request(
                      `/api/qq/groups/${encodeURIComponent(group.group_id)}`,
                      post("PUT", { enabled: false }),
                    );
                    setGroups(await request<Item[]>("/api/qq/groups"));
                  }, false)
                }
              >
                移除
              </button>
            </div>
          ))}
          {groups.length === 0 && (
            <p className="muted">当前没有群聊白名单。私聊不受影响。</p>
          )}
        </div>
      </article>
    </div>
  );

  const renderMcp = () => (
    <div className="page-content">
      <div className="notice">
        新发现的 Tools、Resources 与 Prompts
        默认不授权。请先测试连接，再配置白名单。
      </div>
      {mcps.length ? (
        <div className="manage-list">
          {mcps.map((item) => (
            <article className="manage-card" key={item.name}>
              <div className="manage-card-head">
                <div>
                  <span className="eyebrow">{item.transport}</span>
                  <h2>{item.name}</h2>
                </div>
                <span
                  className={`status-pill ${item.status === "ready" ? "good" : item.enabled ? "warn" : "muted-pill"}`}
                >
                  {item.status}
                </span>
              </div>
              <p>
                {item.url ||
                  [item.command, ...(item.args || [])]
                    .filter(Boolean)
                    .join(" ")}
              </p>
              {item.last_error && <p className="error">{item.last_error}</p>}
              <p className="meta-line">
                授权工具 {item.tool_allowlist?.length || 0} · Secret{" "}
                {item.secret_names?.length || 0}
              </p>
              <div className="card-actions">
                <button
                  className="quiet"
                  onClick={() => void act(() => editMcpConnection(item))}
                >
                  编辑连接
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      const result = await request<Item>(
                        `/api/mcp/servers/${encodeURIComponent(item.name)}/test`,
                        post("POST"),
                      );
                      window.zhiyuDialogs.notify(
                        `连接成功：发现 ${result.tools?.length || 0} 个工具`,
                      );
                      setMcps(await request<Item[]>("/api/mcp/servers"));
                    }, false)
                  }
                >
                  测试连接
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      const result = await request<Item>(
                        `/api/mcp/servers/${encodeURIComponent(item.name)}/test`,
                        post("POST"),
                      );
                      const allowed = await dialog.prompt(
                        `授权工具名（逗号分隔）：${(result.tools || []).join(", ")}`,
                        item.tool_allowlist?.join(", ") || "",
                        { title: "工具白名单" },
                      );
                      if (allowed === null) return;
                      await request(
                        `/api/mcp/servers/${encodeURIComponent(item.name)}/tools/allowlist`,
                        post("PUT", {
                          values: allowed
                            .split(",")
                            .map((x) => x.trim())
                            .filter(Boolean),
                        }),
                      );
                      setMcps(await request<Item[]>("/api/mcp/servers"));
                    })
                  }
                >
                  配置工具授权
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(() => configureMcpAccess(item.name), false)
                  }
                >
                  管理 Tools / Resources / Prompts
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(() => configureMcpSecrets(item), false)
                  }
                >
                  环境变量 / Secret
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(() => readMcpResource(item.name), false)
                  }
                >
                  读取 Resource
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(() => renderMcpPrompt(item.name), false)
                  }
                >
                  运行 Prompt
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      await request(
                        `/api/mcp/servers/${encodeURIComponent(item.name)}/enabled`,
                        post("PUT", { enabled: !item.enabled }),
                      );
                      setMcps(await request<Item[]>("/api/mcp/servers"));
                    })
                  }
                >
                  {item.enabled ? "停用" : "启用"}
                </button>
                <button
                  className="quiet"
                  onClick={() =>
                    void act(async () => {
                      await request(
                        `/api/mcp/servers/${encodeURIComponent(item.name)}/reconnect`,
                        post("POST"),
                      );
                      setMcps(await request<Item[]>("/api/mcp/servers"));
                    }, false)
                  }
                >
                  重连
                </button>
                <button
                  className="danger-button"
                  onClick={() =>
                    void act(async () => {
                      if (
                        !(await dialog.confirm(
                          `移除 MCP ${item.name}？`,
                          "移除 MCP Server",
                        ))
                      )
                        return;
                      await request(
                        `/api/mcp/servers/${encodeURIComponent(item.name)}`,
                        post("DELETE"),
                      );
                      setMcps(await request<Item[]>("/api/mcp/servers"));
                    })
                  }
                >
                  移除
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        !pageLoading && (
          <StateCard
            title="尚未配置 MCP Server"
            description="添加本机 stdio 或远程 MCP 连接。"
            action={
              <button className="primary" onClick={() => void addMcp()}>
                添加 MCP Server
              </button>
            }
          />
        )
      )}
    </div>
  );

  const renderSkills = () => (
    <div className="page-content">
      <div className="notice">
        Skill 内容按需读取；安装不会执行其中代码或自动安装依赖。
      </div>
      {skills.length ? (
        <div className="manage-list">
          {skills.map((item) => (
            <article className="manage-card" key={item.name}>
              <div className="manage-card-head">
                <div>
                  <span className="eyebrow">
                    {item.source_type || "本地"} {item.revision || ""}
                  </span>
                  <h2>{item.name}</h2>
                </div>
                <span
                  className={`status-pill ${item.enabled && item.available ? "good" : "muted-pill"}`}
                >
                  {item.enabled
                    ? item.available
                      ? "已启用"
                      : "缺少依赖"
                    : "已停用"}
                </span>
              </div>
              <p>{item.description || item.error || "暂无描述"}</p>
              <p className="meta-line">
                工具依赖：{(item.required_tools || []).join("、") || "无"} ·
                命令依赖：{(item.missing_bins || []).join("、") || "满足"}
                {item.modified ? " · 本地内容有修改" : ""}
              </p>
              <div className="card-actions">
                {item.managed && (
                  <>
                    <button
                      className="quiet"
                      onClick={() =>
                        void act(async () => {
                          await request(
                            `/api/skills/${encodeURIComponent(item.name)}/enabled`,
                            post("PUT", { enabled: !item.enabled }),
                          );
                          setSkills(await request<Item[]>("/api/skills"));
                        })
                      }
                    >
                      {item.enabled ? "停用" : "启用"}
                    </button>
                    <button
                      className="quiet"
                      onClick={() =>
                        void act(async () => {
                          if (
                            item.modified &&
                            !(await dialog.confirm(
                              "此 Skill 有本地修改，应用更新可能覆盖当前文件。仍要继续预览吗？",
                              "Skill 有本地修改",
                            ))
                          )
                            return;
                          const ref = await dialog.prompt(
                            "目标分支或 Tag（留空使用原来源）",
                            "",
                            { title: "检查 Skill 更新" },
                          );
                          if (ref === null) return;
                          const body = { ref: ref || null };
                          const preview = await request<Item>(
                            `/api/skills/${encodeURIComponent(item.name)}/update-preview`,
                            post("POST", body),
                          );
                          if (!preview.changed) {
                            dialog.notify("已是最新版本");
                            return;
                          }
                          if (
                            !(await dialog.confirm(
                              `更新 ${item.name}？\n${(preview.changed_files || []).slice(0, 20).join("\n")}`,
                              "确认更新",
                            ))
                          )
                            return;
                          await request(
                            `/api/skills/${encodeURIComponent(item.name)}/update`,
                            post("POST", body),
                          );
                          setSkills(await request<Item[]>("/api/skills"));
                        })
                      }
                    >
                      检查更新
                    </button>
                    <button
                      className="danger-button"
                      onClick={() =>
                        void act(async () => {
                          if (
                            !(await dialog.confirm(
                              `将 ${item.name} 移入回收站？`,
                            ))
                          )
                            return;
                          await request(
                            `/api/skills/${encodeURIComponent(item.name)}`,
                            post("DELETE"),
                          );
                          setSkills(await request<Item[]>("/api/skills"));
                          setTrash(await request<Item[]>("/api/skills/trash"));
                        })
                      }
                    >
                      移入回收站
                    </button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        !pageLoading && (
          <StateCard
            title="还没有可用 Skill"
            description="安装本地 Skill 文件夹或 HTTPS Git 仓库。"
            action={
              <button className="primary" onClick={() => void installSkill()}>
                安装 Skill
              </button>
            }
          />
        )
      )}
      <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">TRASH</span>
            <h2>回收站</h2>
          </div>
        </div>
        {trash.map((item) => (
          <div className="list-row" key={item.name}>
            <span className="row-main">{item.name}</span>
            <small>
              {item.source_type} · {stamp(item.trashed_at)}
            </small>
            <button
              className="quiet"
              onClick={() =>
                void act(async () => {
                  await request(
                    `/api/skills/${encodeURIComponent(item.name)}/restore`,
                    post("POST"),
                  );
                  setSkills(await request<Item[]>("/api/skills"));
                  setTrash(await request<Item[]>("/api/skills/trash"));
                })
              }
            >
              恢复
            </button>
          </div>
        ))}
        {trash.length === 0 && <p className="muted">回收站为空</p>}
      </article>
    </div>
  );

  const renderDiagnostics = () => (
    <div className="page-content">
      <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">INBOUND · 最近 100 条</span>
            <h2>渠道事件</h2>
          </div>
        </div>
        {events.map((item) => (
          <div className="table-row" key={item.id}>
            <div>
              <strong>{item.status}</strong>
              <small>{item.id}</small>
            </div>
            <small>{stamp(item.received_at)}</small>
            <small>{item.last_error || "—"}</small>
            {["failed", "pending"].includes(item.status) ? (
              <button
                className="quiet"
                onClick={() =>
                  void act(async () => {
                    await request(
                      `/api/channel-events/${encodeURIComponent(item.id)}/replay`,
                      post("POST"),
                    );
                    setEvents(
                      await request<Item[]>("/api/channel-events?limit=100"),
                    );
                  }, false)
                }
              >
                重放
              </button>
            ) : null}
          </div>
        ))}
        {events.length === 0 && !pageLoading && (
          <p className="muted">暂无事件记录</p>
        )}
      </article>
      <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">OUTBOUND · 最近 100 条</span>
            <h2>消息投递</h2>
          </div>
        </div>
        {deliveries.map((item) => (
          <div className="table-row" key={item.id}>
            <div>
              <strong>{item.status}</strong>
              <small>{item.id}</small>
            </div>
            <small>{item.provider_message_id || "无外部消息 ID"}</small>
            <small>{item.error || "—"}</small>
            {["failed", "unknown"].includes(item.status) ? (
              <button
                className="quiet"
                onClick={() =>
                  void act(async () => {
                    const unknown = item.status === "unknown";
                    if (
                      unknown &&
                      !(await dialog.confirm(
                        "发送结果未知，QQ 可能已经收到。仍要再次发送吗？",
                        "确认再次投递",
                      ))
                    )
                      return;
                    await request(
                      `/api/channel-deliveries/${encodeURIComponent(item.id)}/retry`,
                      post("POST", { allow_unknown: unknown }),
                    );
                    setDeliveries(
                      await request<Item[]>(
                        "/api/channel-deliveries?limit=100",
                      ),
                    );
                  }, false)
                }
              >
                {item.status === "unknown" ? "确认重试" : "重试"}
              </button>
            ) : null}
          </div>
        ))}
        {deliveries.length === 0 && !pageLoading && (
          <p className="muted">暂无投递记录</p>
        )}
      </article>
    </div>
  );

  const renderMemory = () => (
    <div className="memory-page">
      <div className="memory-toolbar">
        <input
          type="search"
          placeholder="搜索长期记忆"
          value={memoryQuery}
          onChange={(event) => setMemoryQuery(event.target.value)}
        />
        <select
          aria-label="记忆层级"
          value={memoryTier}
          onChange={(event) => setMemoryTier(event.target.value)}
        >
          <option value="">全部层级</option>
          <option value="core">核心记忆</option>
          <option value="episodic">情景记忆</option>
        </select>
        <span className="badge">{memories.length} 条</span>
      </div>
      <article className="panel memory-history">
        <header className="section-heading">
          <div>
            <span className="eyebrow">CONSOLIDATION</span>
            <h2>最近记忆沉淀</h2>
          </div>
        </header>
        {consolidationRuns.length ? (
          <div className="memory-run-list">
            {consolidationRuns.map((run) => (
              <div className="memory-run" key={run.id}>
                <span className={`status-dot ${run.status === "failed" ? "warning" : ""}`} />
                <div>
                  <strong>{run.summary || run.status}</strong>
                  <small>{stamp(run.finished_at || run.created_at)} · {run.status}</small>
                  {run.last_error ? <small className="error-text">{run.last_error}</small> : null}
                  {run.details && parseList(run.details).length ? (
                    <details className="memory-sources">
                      <summary>查看本次处理</summary>
                      {parseList(run.details).map((decision, index) => (
                        <p key={`${run.id}-${index}`}>
                          {decision.content || `候选 ${decision.candidate_id || decision.candidate_ids?.join("、") || ""}`} · {decision.decision}
                          {decision.reason ? ` · ${decision.reason}` : ""}
                        </p>
                      ))}
                    </details>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : <p className="muted">还没有沉淀记录；系统会在新观察达到条件后自动整理。</p>}
      </article>
      {memories.length ? (
        <div className="memory-list">
          {memories.map((item) => (
            <article className="memory-card" key={item.id}>
              <header>
                <span>
                  {item.type} · {item.tier}
                </span>
                <span>{item.confirmation_status === "needs_confirmation" ? "90 天未确认" : item.promotion_status === "deferred" ? "待补充证据" : item.promotion_status === "pending" ? "待沉淀" : item.promotion_status === "promoted" ? "已沉淀" : item.origin}</span>
              </header>
              <p>{item.content}</p>
              <div className="memory-actions">
                {item.confirmation_status === "needs_confirmation" ? (
                  <button onClick={() => void act(async () => {
                    await request(`/api/memories/${encodeURIComponent(item.id)}/confirm`, post("POST"));
                    const params = new URLSearchParams();
                    if (memoryQuery) params.set("query", memoryQuery);
                    if (memoryTier) params.set("tier", memoryTier);
                    setMemories(await request<Item[]>(`/api/memories?${params}`));
                  }, false)}>仍在进行</button>
                ) : null}
                {item.tier === "episodic" && item.promotion_status !== "promoted" ? (
                  <button onClick={() => void act(async () => {
                    await request(`/api/memories/${encodeURIComponent(item.id)}/keep`, post("POST"));
                    const params = new URLSearchParams();
                    if (memoryQuery) params.set("query", memoryQuery);
                    if (memoryTier) params.set("tier", memoryTier);
                    setMemories(await request<Item[]>(`/api/memories?${params}`));
                  }, false)}>保留为长期记忆</button>
                ) : null}
                <button
                  onClick={() =>
                    void act(async () => {
                    const content = await dialog.prompt(
                      "修改记忆内容",
                      item.content,
                      { title: "纠正长期记忆" },
                    );
                    if (!content || content === item.content) return;
                    await request(
                      `/api/memories/${encodeURIComponent(item.id)}`,
                      post("PATCH", { content }),
                    );
                    const params = new URLSearchParams();
                    if (memoryQuery) params.set("query", memoryQuery);
                    if (memoryTier) params.set("tier", memoryTier);
                    setMemories(
                      await request<Item[]>(`/api/memories?${params}`),
                    );
                    }, false)
                  }
                >纠正</button>
                <button className="danger-button" onClick={() => void act(async () => {
                  if (!(await dialog.confirm("删除这条记忆及其来源关系？", "删除记忆"))) return;
                  const response = await fetch(`/api/memories/${encodeURIComponent(item.id)}`, { method: "DELETE" });
                  if (!response.ok) throw new Error(`删除失败：${response.status}`);
                  const params = new URLSearchParams();
                  if (memoryQuery) params.set("query", memoryQuery);
                  if (memoryTier) params.set("tier", memoryTier);
                  setMemories(await request<Item[]>(`/api/memories?${params}`));
                }, false)}>删除</button>
              </div>
              {item.sources?.length ? (
                <details className="memory-sources">
                  <summary>来源证据 · {item.sources.length}</summary>
                  {item.sources.map((source: Item, index: number) => (
                    <p key={`${item.id}-source-${index}`}>{source.content || "来源已不可用"}<small>{stamp(source.observed_at)} · {source.source_kind}</small></p>
                  ))}
                </details>
              ) : item.source_content ? <details className="memory-sources"><summary>查看来源</summary><p>{item.source_content}</p></details> : null}
            </article>
          ))}
        </div>
      ) : (
        !pageLoading && (
          <StateCard
            title="没有匹配的记忆"
            description="尝试调整搜索内容或层级筛选。"
          />
        )
      )}
    </div>
  );

  const pageBody = useMemo(() => {
    if (page === "overview") return renderOverview();
    if (page === "providers") return renderProviders();
    if (page === "channels") return renderChannels();
    if (page === "mcp") return renderMcp();
    if (page === "skills") return renderSkills();
    if (page === "diagnostics") return renderDiagnostics();
    if (page === "memory") return renderMemory();
    return null;
    // Render is intentionally driven by the page-local API state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    page,
    overview,
    overviewLoading,
    providers,
    qq,
    channels,
    groups,
    mcps,
    skills,
    trash,
    events,
    deliveries,
    memories,
    memoryQuery,
    memoryTier,
    pageLoading,
  ]);

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
          <>
            <header className="topbar">
              <div>
                <small>当前会话</small>
                <h1>{conversationTitle}</h1>
              </div>
              <div className="badge">
                {overview?.model?.model
                  ? `${overview.model.provider} · ${overview.model.model}`
                  : "默认模型未配置"}
              </div>
            </header>
            <div className="messages">
              {messages.length ? (
                messages.map((item, index) => (
                  <div
                    key={`${item.id || index}`}
                    className={`message ${item.role} ${item.error ? "error" : ""}`}
                  >
                    <span className="role">
                      {item.role === "user" ? "你" : "知语"}
                    </span>
                    <span className="content">
                      {item.content}
                      {item.error && (
                        <>
                          <br />
                          <small>运行失败：{item.error}</small>
                        </>
                      )}
                      {item.cancelled && <small>已停止生成</small>}
                      {item.pending && !item.content && (
                        <span className="typing">正在生成…</span>
                      )}
                    </span>
                  </div>
                ))
              ) : (
                <div className="empty-state">
                  <span>知</span>
                  <h2>有什么想一起处理的？</h2>
                  <p>对话、工具与长期记忆都由同一个本地 Agent 处理。</p>
                </div>
              )}
            </div>
            <div className="activity" aria-live="polite">
              {activity}
            </div>
            <form
              className="composer"
              onSubmit={(event) => void sendMessage(event)}
            >
              <textarea
                rows={1}
                placeholder="输入消息，Enter 发送，Shift + Enter 换行"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
              />
              <button
                className="send"
                type={busy ? "button" : "submit"}
                aria-label={busy ? "停止生成" : "发送"}
                onClick={busy ? () => void cancelRun() : undefined}
              >
                {busy ? "■" : "↑"}
              </button>
            </form>
          </>
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
            {pageLoading && <div className="loading-line">正在加载…</div>}
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
      </main>
    </div>
  );
}

function StateCard({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <article className="empty-panel">
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {action}
    </article>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
