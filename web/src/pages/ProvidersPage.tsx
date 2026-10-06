import { useCallback, useEffect, useState } from "react";
import { errorText, post, request } from "../api";
import { StateCard } from "../components/StateCard";
import type { Item } from "../types";

type Props = {
  reloadKey: number;
  onLoadError: (error: string) => void;
  act: (action: () => Promise<unknown>, refresh?: boolean) => Promise<void>;
  addProvider: () => Promise<void>;
};

export function ProvidersPage({ reloadKey, onLoadError, act, addProvider }: Props) {
  const [providers, setProviders] = useState<Item[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const dialog = window.zhiyuDialogs;
  const loadProviders = useCallback(async () => {
    const items = await request<Item[]>("/api/providers");
    return Promise.all(
      items.map(async (item) => ({
        ...item,
        detail: await request<Item>(
          `/api/providers/${encodeURIComponent(item.name)}`,
        ),
      })),
    );
  }, []);
  useEffect(() => {
    let alive = true;
    setPageLoading(true);
    void loadProviders()
      .then((items) => {
        if (alive) setProviders(items);
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
  }, [loadProviders, onLoadError, reloadKey]);
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
      setProviders(await loadProviders());
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
      setProviders(await loadProviders());
    }, false);
  }
  return (
    <div className="page-content">
      {pageLoading && <div className="loading-line">正在加载…</div>}
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
}
