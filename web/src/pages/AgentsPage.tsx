import { useEffect, useState } from "react";
import { post, request, errorText } from "../api";
import { StateCard } from "../components/StateCard";
import type { Item } from "../types";

type Props = {
  agents: Item[];
  selectedId: string | null;
  onSelect: (id: string | null) => Promise<void>;
  onChanged: () => Promise<void>;
};

export function AgentsPage({ agents, selectedId, onSelect, onChanged }: Props) {
  const [models, setModels] = useState<Item[]>([]);
  useEffect(() => {
    void request<Item[]>("/api/providers").then(async (providers) => {
      const details = await Promise.all(providers.filter((provider) => provider.enabled && provider.configured).map((provider) => request<Item>(`/api/providers/${encodeURIComponent(provider.name)}`)));
      setModels(details.flatMap((provider) => (provider.models || []).map((model: Item) => ({ ...model, provider: provider.name }))));
    }).catch(() => undefined);
  }, []);

  async function edit(agent?: Item) {
    const values = await window.zhiyuDialogs.form(
      agent ? `编辑 ${agent.name}` : "创建智能体",
      "名称和角色可随时修改。每个智能体独立保存会话、记忆和插件权限。",
      [
        { name: "name", label: "名称", value: agent?.name || "", required: true },
        { name: "description", label: "简介", value: agent?.description || "" },
        { name: "personality", label: "性格", type: "textarea", value: agent?.personality || "" },
        { name: "background", label: "背景", type: "textarea", value: agent?.background || "" },
        { name: "speaking_style", label: "说话风格", value: agent?.speaking_style || "" },
        { name: "system_prompt", label: "角色指令", type: "textarea", value: agent?.system_prompt || "", description: "填写时以此作为完整角色设定；留空则使用上面的性格、背景和风格。" },
        { name: "opening_message", label: "开场白", type: "textarea", value: agent?.opening_message || "" },
        { name: "world_setting", label: "世界观", type: "textarea", value: agent?.world_setting || "" },
        { name: "initial_scene", label: "初始场景", type: "textarea", value: agent?.initial_scene || "" },
        { name: "behavior_preferences", label: "行为偏好", type: "textarea", value: agent?.behavior_preferences || "" },
        { name: "default_model_id", label: "默认模型", type: "select", value: agent?.default_model_id || "", options: [
          { value: "", label: "使用全局默认模型" },
          ...models.filter((model) => model.enabled).map((model) => ({ value: model.id, label: `${model.provider} · ${model.display_name || model.model_name}` })),
        ] },
      ],
      agent ? "保存" : "创建",
    );
    if (!values) return;
    try {
      const body = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, value || null]));
      await request(agent ? `/api/agents/${encodeURIComponent(agent.id)}` : "/api/agents", post(agent ? "PUT" : "POST", body));
      await onChanged();
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "保存失败");
    }
  }

  async function setAvatar(agent: Item, file?: File) {
    try {
      const response = await fetch(`/api/agents/${encodeURIComponent(agent.id)}/avatar`, {
        method: file ? "PUT" : "DELETE",
        headers: { "X-Zhiyu-Request": "1", ...(file ? { "Content-Type": file.type } : {}) },
        body: file,
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.detail || "头像更新失败");
      }
      await onChanged();
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "头像更新失败");
    }
  }

  async function exportTemplate(agent: Item) {
    try {
      const response = await fetch(`/api/agents/${encodeURIComponent(agent.id)}/template`);
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "导出失败");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${agent.name || "角色"}.json`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "导出失败");
    }
  }

  async function importTemplate(file?: File) {
    if (!file) return;
    try {
      if (file.size > 4 * 1024 * 1024) throw new Error("角色模板不能超过 4 MiB");
      const payload = JSON.parse(await file.text());
      const result = await request<Item>("/api/agents/import", post("POST", payload));
      await onChanged();
      if (result.warning) await window.zhiyuDialogs.alert(result.warning, "角色已导入");
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "导入失败");
    }
  }

  async function remove(agent: Item) {
    if (!(await window.zhiyuDialogs.confirm(`删除 ${agent.name}？该角色的会话、记忆、插件配置和头像也会删除；共享用户资料会保留。`, "删除智能体"))) return;
    try {
      await request(`/api/agents/${encodeURIComponent(agent.id)}`, post("DELETE"));
      if (selectedId === agent.id) await onSelect(null);
      await onChanged();
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "删除失败");
    }
  }

  return (
    <div className="page-content">
      <div className="notice">选择智能体后，「关于彼此」「日记」「插件」只管理它的内容。新智能体从空白记忆和空插件授权开始。</div>
      <div className="button-row"><button className="primary" onClick={() => void edit()}>创建智能体</button><label className="quiet template-upload">导入角色模板<input type="file" accept="application/json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importTemplate(file); event.currentTarget.value = ""; }} /></label></div>
      <div className="manage-list">
        <article className="manage-card">
          <div className="manage-card-head"><h2>星栖</h2><span className="status-pill">默认助手</span></div>
          <p>保留原有助手设定和独立记忆空间。</p>
          <button className="quiet" onClick={() => void onSelect(null)}>{selectedId === null ? "当前智能体" : "开始对话"}</button>
        </article>
        {agents.map((agent) => (
          <article className="manage-card" key={agent.id}>
            <div className="manage-card-head">
              {agent.avatar ? <img className="agent-avatar" src={`/api/agents/${encodeURIComponent(agent.id)}/avatar`} alt="" /> : null}
              <h2>{agent.name}</h2>{selectedId === agent.id && <span className="status-pill good">当前智能体</span>}
            </div>
            <p>{agent.description || agent.personality || "尚未填写角色设定"}</p>
            <div className="card-actions">
              <button className="primary" onClick={() => void onSelect(agent.id)}>开始对话</button>
              <button className="quiet" onClick={() => void edit(agent)}>编辑角色</button>
              <button className="quiet" onClick={() => void exportTemplate(agent)}>导出模板</button>
              <label className="quiet avatar-upload">{agent.avatar ? "更换头像" : "上传头像"}<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) void setAvatar(agent, file); event.currentTarget.value = ""; }} /></label>
              {agent.avatar && <button className="quiet" onClick={() => void setAvatar(agent)}>移除头像</button>}
              <button className="danger-button" onClick={() => void remove(agent)}>删除</button>
            </div>
          </article>
        ))}
      </div>
      {!agents.length && <StateCard title="创建你的第一个智能体" description="名字由你决定，也可以分别赋予不同的角色。" />}
    </div>
  );
}
