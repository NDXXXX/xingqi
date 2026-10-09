import { useEffect, useState } from "react";
import { errorText, post } from "../api";
import { StateCard } from "../components/StateCard";
import { useAgentRequest } from "../agentScope";
import type { Item } from "../types";

type Props = {
  reloadKey: number;
  onLoadError: (error: string) => void;
  act: (action: () => Promise<unknown>, refresh?: boolean) => Promise<void>;
  addMcp: () => Promise<void>;
};

export function McpPage({ reloadKey, onLoadError, act, addMcp }: Props) {
  const request = useAgentRequest();
  const [mcps, setMcps] = useState<Item[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const dialog = window.zhiyuDialogs;
  useEffect(() => {
    let alive = true;
    setPageLoading(true);
    void request<Item[]>("/api/mcp/servers")
      .then((items) => {
        if (alive) setMcps(items);
      })
      .catch((error) => {
        if (alive) onLoadError(errorText(error));
      })
      .finally(() => {
        if (alive) setPageLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [onLoadError, reloadKey, request]);
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
  return (
    <div className="page-content">
      {pageLoading && <div className="loading-line">正在加载…</div>}
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
}
