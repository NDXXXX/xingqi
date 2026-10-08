import { useCallback, useRef, useState, type FormEvent } from "react";
import { errorText, post, request } from "../api";
import { isCurrentRequest } from "../chatState";
import type { Item } from "../types";

export function useChatSession({
  conversationId,
  refreshConversations,
  onConversationCreated,
  onErrorClear,
  onRequestError,
}: {
  conversationId: string | null;
  refreshConversations: () => Promise<void>;
  onConversationCreated: (id: string) => void;
  onErrorClear: () => void;
  onRequestError: (error: string) => void;
}) {
  const [messages, setMessages] = useState<Item[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState("");
  const streamRef = useRef<{
    controller: AbortController;
    runId: string | null;
    conversationId: string | null;
  } | null>(null);

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
  const clearMessages = useCallback(() => setMessages([]), []);

  const sendMessage = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      const text = draft.trim();
      if (!text || busy) return;
      const requestId = conversationId;
      const assistantMessageId = crypto.randomUUID();
      const controller = new AbortController();
      const run = {
        controller,
        runId: null as string | null,
        conversationId: requestId,
      };
      streamRef.current = run;
      setBusy(true);
      setDraft("");
      onErrorClear();
      setMessages((current) => [
        ...current,
        { role: "user", content: text },
        { id: assistantMessageId, role: "assistant", content: "", pending: true },
      ]);
      setActivity("正在思考…");
      const updateAssistant = (change: (previous: Item) => Item) => {
        if (!isCurrentRequest(streamRef.current, run)) return;
        setMessages((current) =>
          current.map((item) =>
            item.id === assistantMessageId ? change(item) : item,
          ),
        );
      };
      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Zhiyu-Request": "1" },
          body: JSON.stringify({ message: text, conversation_id: requestId }),
          signal: controller.signal,
        });
        if (!response.ok || !response.body)
          throw new Error("无法启动对话");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let terminalEvent = false;
        let failed = false;
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
              if (requestId === null)
                onConversationCreated(message.conversation_id);
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
            if (message.type === "error") {
              terminalEvent = true;
              failed = true;
              onRequestError(errorText(message.error));
              updateAssistant((item) => ({
                ...item,
                pending: false,
                error: errorText(message.error),
                content: item.content || "",
              }));
            }
            if (message.type === "done") {
              terminalEvent = true;
              updateAssistant((item) => ({
                ...item,
                content: item.content || message.response,
                pending: false,
              }));
            }
          }
          if (done) break;
        }
        if (isCurrentRequest(streamRef.current, run)) {
          setActivity("");
          if (!terminalEvent) throw new Error("对话连接已结束，但服务未返回最终结果");
          if (!failed) await refreshConversations();
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          if (isCurrentRequest(streamRef.current, run))
            onRequestError(errorText(error));
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
    },
    [
      busy,
      conversationId,
      draft,
      onConversationCreated,
      onErrorClear,
      onRequestError,
      refreshConversations,
    ],
  );

  return {
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
  };
}
