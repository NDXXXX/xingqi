import { useCallback, useRef, useState, type FormEvent } from "react";
import { errorText, post, request } from "../api";
import { isCurrentRequest } from "../chatState";
import { modelDisclosureKey } from "../modelPrivacy";
import type { Item } from "../types";

export function useChatSession({
  conversationId,
  characterId,
  refreshConversations,
  onConversationCreated,
  onErrorClear,
  onRequestError,
  selectedModel,
  disclosureModel,
}: {
  conversationId: string | null;
  characterId: string | null;
  refreshConversations: () => Promise<void>;
  onConversationCreated: (id: string) => void;
  onErrorClear: () => void;
  onRequestError: (error: string) => void;
  selectedModel: { providerId: string; model: string } | null;
  disclosureModel: { providerId: string; providerName: string; baseUrl?: string | null; remote: boolean } | null;
}) {
  const [messages, setMessages] = useState<Item[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState("");
  const disclosedRemoteModels = useRef(new Set<string>());
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
  const confirmRemoteModel = useCallback(async () => {
    if (disclosureModel && !disclosureModel.remote) return true;
    const key = disclosureModel
      ? modelDisclosureKey({ provider_id: disclosureModel.providerId, base_url: disclosureModel.baseUrl })
      : "unknown-model-endpoint";
    if (disclosedRemoteModels.current.has(key)) return true;
    const providerName = disclosureModel?.providerName || "当前默认模型服务";
    const confirmed = await window.zhiyuDialogs.confirm(
      `本轮对话上下文可能发送给「${providerName}」，包括当前会话内容、角色设定及用于回答的记忆。当前无法确认该端点属于本地服务，请确认你接受该服务商的数据处理方式。`,
      "远程模型数据提示",
    );
    if (confirmed) disclosedRemoteModels.current.add(key);
    return confirmed;
  }, [disclosureModel]);

  const runMessage = useCallback(
    async (text: string, regenerate = false, existingAssistantId?: string) => {
      if (!text || busy) return;
      const requestId = conversationId;
      const assistantMessageId = existingAssistantId || crypto.randomUUID();
      const controller = new AbortController();
      const run = {
        controller,
        runId: null as string | null,
        conversationId: requestId,
      };
      streamRef.current = run;
      setBusy(true);
      if (!regenerate) setDraft("");
      onErrorClear();
      setMessages((current) => existingAssistantId
        ? current.map((item) => item.id === assistantMessageId
          ? { ...item, content: "", error: undefined, pending: true }
          : item)
        : [
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
          body: JSON.stringify({
            message: text,
            conversation_id: requestId,
            character_id: characterId,
            provider_id: selectedModel?.providerId,
            model: selectedModel?.model,
            regenerate,
          }),
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
      characterId,
      onConversationCreated,
      onErrorClear,
      onRequestError,
      refreshConversations,
      selectedModel,
      disclosureModel,
    ],
  );

  const sendMessage = useCallback((event: FormEvent) => {
    event.preventDefault();
    void (async () => {
      if (!(await confirmRemoteModel())) return;
      await runMessage(draft.trim());
    })();
  }, [confirmRemoteModel, draft, runMessage]);

  const retryLast = useCallback(() => {
    if (busy) return;
    const assistantIndex = messages.map((item) => item.role === "assistant" && item.error ? true : false).lastIndexOf(true);
    if (assistantIndex < 0) return;
    const userMessage = [...messages.slice(0, assistantIndex)].reverse().find((item) => item.role === "user");
    const assistantMessage = messages[assistantIndex];
    if (!userMessage || !assistantMessage.id) return;
    void (async () => {
      if (!(await confirmRemoteModel())) return;
      await runMessage(userMessage.content || "", Boolean(conversationId), assistantMessage.id);
    })();
  }, [busy, confirmRemoteModel, conversationId, messages, runMessage]);

  return {
    messages,
    setMessages,
    draft,
    setDraft,
    busy,
    activity,
    setActivity,
    sendMessage,
    retryLast,
    cancelRun,
    clearMessages,
  };
}
