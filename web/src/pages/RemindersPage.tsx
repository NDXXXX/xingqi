import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorText, post, request } from "../api";
import { StateCard } from "../components/StateCard";
import type { Item } from "../types";

const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const localInput = (iso: string) => {
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const statusNames: Record<string, string> = {
  pending: "等待中", paused: "已暂停", due: "已到期", delivered: "已发送",
  completed: "已完成", failed: "发送失败", sending: "发送中",
};

export function RemindersPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [content, setContent] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [channel, setChannel] = useState("local");
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => setItems(await request<Item[]>("/api/scheduled-tasks")), []);
  useEffect(() => { void refresh().catch((e) => setError(errorText(e))); }, [refresh]);

  const reset = () => { setEditing(null); setContent(""); setDueAt(""); setChannel("local"); };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!dueAt) return;
    setBusy(true); setError("");
    try {
      const body = { content, due_at: new Date(dueAt).toISOString(), timezone, channel };
      await request(`/api/scheduled-tasks${editing ? `/${encodeURIComponent(editing)}` : ""}`, post(editing ? "PUT" : "POST", body));
      reset(); await refresh();
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  };
  const action = async (id: string, method: string, suffix = "", body?: unknown) => {
    setError("");
    try { await request(`/api/scheduled-tasks/${encodeURIComponent(id)}${suffix}`, post(method, body)); await refresh(); }
    catch (e) { setError(errorText(e)); }
  };

  return <section className="page-content reminders-page">
    <p className="muted">按本机时区安排一次性提醒。QQ 提醒只会发送给当前配置的主人账号。</p>
    <form className="reminder-form" onSubmit={(event) => void submit(event)}>
      <label>提醒内容<input required maxLength={500} value={content} onChange={(event) => setContent(event.target.value)} placeholder="例如：提交周报" /></label>
      <label>提醒时间<input required type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label>
      <label>提醒方式<select value={channel} onChange={(event) => setChannel(event.target.value)}><option value="local">本机提醒</option><option value="qq">QQ 私聊</option></select></label>
      <div className="reminder-form-actions"><button className="primary" disabled={busy}>{editing ? "保存修改" : "添加提醒"}</button>{editing && <button type="button" className="quiet" onClick={reset}>取消</button>}</div>
    </form>
    {error && <StateCard title="提醒操作失败" description={error} />}
    {items.length === 0 ? <StateCard title="还没有提醒" description="创建一条本机或 QQ 私聊提醒。" /> : <div className="reminder-list">
      {items.map((item) => <article className="reminder-item" key={item.id}>
        <div className="reminder-main"><strong>{item.content}</strong><span>{new Date(item.due_at).toLocaleString()} · {item.channel === "qq" ? "QQ 私聊" : "本机"} · {statusNames[item.status] || item.status}</span>{item.last_error && <small role="alert">{item.last_error}</small>}</div>
        <div className="reminder-actions">
          {item.status === "pending" && <button className="quiet" onClick={() => void action(item.id, "PATCH", "/enabled", { enabled: false })}>暂停</button>}
          {item.status === "paused" && <button className="quiet" onClick={() => void action(item.id, "PATCH", "/enabled", { enabled: true })}>恢复</button>}
          {item.status === "due" && <button className="quiet" onClick={() => void action(item.id, "POST", "/complete")}>完成</button>}
          {item.status === "failed" && <button className="quiet" onClick={() => void action(item.id, "POST", "/retry")}>重试</button>}
          {["pending", "paused", "failed"].includes(item.status) && <button className="quiet" onClick={() => { setEditing(item.id); setContent(item.content); setDueAt(localInput(item.due_at)); setChannel(item.channel); }}>编辑</button>}
          {item.status !== "sending" && <button className="quiet" onClick={() => void action(item.id, "DELETE")}>删除</button>}
        </div>
      </article>)}
    </div>}
  </section>;
}
