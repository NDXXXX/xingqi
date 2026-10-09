import type { FormEvent } from "react";
import type { Item } from "../types";

export function ChatPage({
  conversationTitle,
  agentName,
  modelLabel,
  requestError,
  messages,
  activity,
  draft,
  busy,
  onSubmit,
  onDraftChange,
  onCancel,
}: {
  conversationTitle: string;
  agentName: string;
  modelLabel: string;
  requestError: string;
  messages: Item[];
  activity: string;
  draft: string;
  busy: boolean;
  onSubmit: (event: FormEvent) => void;
  onDraftChange: (value: string) => void;
  onCancel: () => void;
}) {
  return (
    <>
      <header className="topbar">
        <div>
          <small>当前会话</small>
          <h1>{conversationTitle}</h1>
        </div>
        <div className="badge">{modelLabel}</div>
      </header>
      {requestError && !messages.some((item) => item.error) && (
        <div className="error-text" role="alert">
          {requestError}
        </div>
      )}
      <div className="messages">
        {messages.length ? (
          messages.map((item, index) => (
            <div
              key={`${item.id || index}`}
              className={`message ${item.role} ${item.error ? "error" : ""}`}
            >
              <span className="role">{item.role === "user" ? "你" : agentName}</span>
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
            <span>{agentName.slice(0, 1)}</span>
            <h2>有什么想一起处理的？</h2>
            <p>与当前智能体对话，工具和长期记忆按它的权限使用。</p>
          </div>
        )}
      </div>
      <div className="activity" aria-live="polite">
        {activity}
      </div>
      <form className="composer" onSubmit={onSubmit}>
        <textarea
          rows={1}
          placeholder="输入消息，Enter 发送，Shift + Enter 换行"
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
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
          onClick={busy ? onCancel : undefined}
        >
          {busy ? "■" : "↑"}
        </button>
      </form>
    </>
  );
}
