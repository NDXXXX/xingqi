import { useEffect, useState } from "react";
import { post, errorText } from "../api";
import { useAgentRequest } from "../agentScope";
import { StateCard } from "../components/StateCard";
import type { Item } from "../types";

export function AgentAboutPage({ agent, reloadKey, onLoadError }: { agent: Item; reloadKey: number; onLoadError: (error: string) => void }) {
  const request = useAgentRequest();
  const [memories, setMemories] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    void request<Item[]>("/api/memories?tier=core").then((items) => { if (alive) setMemories(items); })
      .catch((error) => { if (alive) onLoadError(errorText(error)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [request, reloadKey, onLoadError]);

  async function change(item: Item, remove = false) {
    try {
      if (remove) {
        if (!(await window.zhiyuDialogs.confirm("从此智能体的记忆文件中删除这条内容？", "删除记忆"))) return;
        await request(`/api/memories/${encodeURIComponent(item.id)}`, post("DELETE"));
      } else {
        const content = await window.zhiyuDialogs.prompt("修改此智能体的长期记忆", item.content, { title: "编辑记忆" });
        if (!content?.trim()) return;
        await request(`/api/memories/${encodeURIComponent(item.id)}`, post("PATCH", { content }));
      }
      setMemories(await request<Item[]>("/api/memories?tier=core"));
    } catch (error) { onLoadError(errorText(error)); }
  }

  return <div className="page-content">
    <article className="panel assistant-profile-intro">
      <h2>关于 {agent.name}</h2>
      <p>{agent.description || "独立智能体"}</p>
      <p>{agent.system_prompt || [agent.personality, agent.background, agent.speaking_style].filter(Boolean).join("\n") || "角色设定为空，可在「智能体」中编辑。"}</p>
    </article>
    <section className="panel about-memory-panel">
      <div className="panel-heading"><h2>共同记忆</h2><span className="badge">{memories.length} 条</span><button className="danger-button" onClick={() => void (async () => {
        if (!(await window.zhiyuDialogs.confirm("清空此智能体的记忆？会保留聊天记录，旧记录不再参与历史召回。", "清空记忆"))) return;
        try { await request("/api/memories/clear", post("POST")); setMemories([]); } catch (error) { onLoadError(errorText(error)); }
      })()}>清空记忆</button></div>
      {loading ? <div className="loading-line">正在加载…</div> : memories.map((item) => <article className="about-memory-entry" key={item.id}>
        <div><small>{item.type}</small><p>{item.content}</p></div>
        <div className="about-memory-actions"><button className="quiet" onClick={() => void change(item)}>编辑</button><button className="quiet" onClick={() => void change(item, true)}>删除</button></div>
      </article>)}
      {!loading && !memories.length && <StateCard title="还没有共同记忆" description="告诉它需要记住的资料或偏好，记忆只属于这个智能体。" />}
    </section>
  </div>;
}
