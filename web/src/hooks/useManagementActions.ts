import { useCallback } from "react";
import { post, request } from "../api";
import type { Item } from "../types";

type Act = (action: () => Promise<unknown>, refresh?: boolean) => Promise<void>;

export function useManagementActions(
  act: Act,
  onChanged: () => void,
) {
  const dialog = window.zhiyuDialogs;

  const addProvider = useCallback(async () => {
    const values = await dialog.form(
      "添加模型服务",
      "API Key 不会再次显示。",
      [
        { name: "name", label: "Provider 名称", required: true, placeholder: "例如 deepseek" },
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
      onChanged();
    });
  }, [act, dialog, onChanged]);

  const addMcp = useCallback(async () => {
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
          args: JSON.parse(String(values.args || "[]")) as string[],
          url: transport === "stdio" ? null : values.url,
          enabled: false,
        }),
      );
      onChanged();
    });
  }, [act, dialog, onChanged]);

  const installSkill = useCallback(async () => {
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
      onChanged();
    });
  }, [act, dialog, onChanged]);

  return { addProvider, addMcp, installSkill };
}
