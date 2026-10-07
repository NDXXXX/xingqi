import { useCallback, useEffect, useState } from "react";
import { errorText, post, request } from "../api";
import { StateCard } from "../components/StateCard";
import { parseList, stamp } from "../format";
import type { Item } from "../types";

function queryString(query: string, tier: string) {
  const params = new URLSearchParams();
  if (query) params.set("query", query);
  if (tier) params.set("tier", tier);
  return params.toString();
}

export function MemoryPage({ reloadKey }: { reloadKey: number }) {
  const [memories, setMemories] = useState<Item[]>([]);
  const [consolidationRuns, setConsolidationRuns] = useState<Item[]>([]);
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryTier, setMemoryTier] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const dialog = window.zhiyuDialogs;

  const load = useCallback(async (isAlive: () => boolean = () => true) => {
    if (isAlive()) {
      setLoading(true);
      setLoadError("");
    }
    const params = queryString(memoryQuery, memoryTier);
    try {
      const [items, runs] = await Promise.all([
        request<Item[]>(`/api/memories?${params}`),
        request<Item[]>("/api/memory-consolidation-runs?limit=5"),
      ]);
      if (isAlive()) {
        setMemories(items);
        setConsolidationRuns(runs);
      }
    } catch (error) {
      if (isAlive()) setLoadError(errorText(error));
    } finally {
      if (isAlive()) setLoading(false);
    }
  }, [memoryQuery, memoryTier]);

  useEffect(() => {
    let alive = true;
    void load(() => alive);
    return () => {
      alive = false;
    };
  }, [load, reloadKey]);

  async function act(action: () => Promise<void>) {
    try {
      await action();
    } catch (error) {
      void dialog.alert(errorText(error), "操作失败");
    }
  }

  async function refreshMemories() {
    const params = queryString(memoryQuery, memoryTier);
    setMemories(await request<Item[]>(`/api/memories?${params}`));
  }

  async function confirmMemory(id: string) {
    await request(`/api/memories/${encodeURIComponent(id)}/confirm`, post("POST"));
    await refreshMemories();
  }

  async function keepMemory(id: string) {
    await request(`/api/memories/${encodeURIComponent(id)}/keep`, post("POST"));
    await refreshMemories();
  }

  async function editMemory(item: Item) {
    const content = await dialog.prompt("修改记忆内容", item.content, {
      title: "纠正长期记忆",
    });
    if (!content || content === item.content) return;
    await request(
      `/api/memories/${encodeURIComponent(item.id)}`,
      post("PATCH", { content }),
    );
    await refreshMemories();
  }

  async function deleteMemory(item: Item) {
    if (!(await dialog.confirm("删除这条记忆及其来源关系？", "删除记忆")))
      return;
    const response = await fetch(
      `/api/memories/${encodeURIComponent(item.id)}`,
      { method: "DELETE", headers: { "X-Zhiyu-Request": "1" } },
    );
    if (!response.ok) throw new Error(`删除失败：${response.status}`);
    await refreshMemories();
  }

  return (
    <div className="memory-page">
      {loading && <div className="loading-line">正在加载…</div>}
      {loadError ? (
        <div className="page-content" role="alert">
          <StateCard
            title="页面数据读取失败"
            description={loadError}
            action={
              <button className="quiet" onClick={() => void load()}>
                重试
              </button>
            }
          />
        </div>
      ) : (
        <>
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
                    <span
                      className={`status-dot ${run.status === "failed" ? "warning" : ""}`}
                    />
                    <div>
                      <strong>{run.summary || run.status}</strong>
                      <small>
                        {stamp(run.finished_at || run.created_at)} · {run.status}
                      </small>
                      {run.last_error ? (
                        <small className="error-text">{run.last_error}</small>
                      ) : null}
                      {run.details && parseList(run.details).length ? (
                        <details className="memory-sources">
                          <summary>查看本次处理</summary>
                          {parseList(run.details).map((decision, index) => (
                            <p key={`${run.id}-${index}`}>
                              {decision.content ||
                                `候选 ${decision.candidate_id || decision.candidate_ids?.join("、") || ""}`}
                              {" · "}
                              {decision.decision}
                              {decision.reason ? ` · ${decision.reason}` : ""}
                            </p>
                          ))}
                        </details>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                还没有沉淀记录；系统会在新观察达到条件后自动整理。
              </p>
            )}
          </article>
          {memories.length ? (
            <div className="memory-list">
              {memories.map((item) => (
                <article className="memory-card" key={item.id}>
                  <header>
                    <span>
                      {item.type} · {item.tier}
                    </span>
                    <span>
                      {item.confirmation_status === "needs_confirmation"
                        ? "90 天未确认"
                        : item.promotion_status === "deferred"
                          ? "待补充证据"
                          : item.promotion_status === "pending"
                            ? "待沉淀"
                            : item.promotion_status === "promoted"
                              ? "已沉淀"
                              : item.origin}
                    </span>
                  </header>
                  <p>{item.content}</p>
                  <div className="memory-actions">
                    {item.confirmation_status === "needs_confirmation" ? (
                      <button
                        onClick={() => void act(() => confirmMemory(item.id))}
                      >
                        仍在进行
                      </button>
                    ) : null}
                    {item.tier === "episodic" &&
                    item.promotion_status !== "promoted" ? (
                      <button
                        onClick={() => void act(() => keepMemory(item.id))}
                      >
                        保留为长期记忆
                      </button>
                    ) : null}
                    <button onClick={() => void act(() => editMemory(item))}>
                      纠正
                    </button>
                    <button
                      className="danger-button"
                      onClick={() => void act(() => deleteMemory(item))}
                    >
                      删除
                    </button>
                  </div>
                  {item.sources?.length ? (
                    <details className="memory-sources">
                      <summary>来源证据 · {item.sources.length}</summary>
                      {item.sources.map((source: Item, index: number) => (
                        <p key={`${item.id}-source-${index}`}>
                          {source.content || "来源已不可用"}
                          <small>
                            {stamp(source.observed_at)} · {source.source_kind}
                          </small>
                        </p>
                      ))}
                    </details>
                  ) : item.source_content ? (
                    <details className="memory-sources">
                      <summary>查看来源</summary>
                      <p>{item.source_content}</p>
                    </details>
                  ) : null}
                </article>
              ))}
            </div>
          ) : (
            !loading && (
              <StateCard
                title="没有匹配的记忆"
                description="尝试调整搜索内容或层级筛选。"
              />
            )
          )}
        </>
      )}
    </div>
  );
}
