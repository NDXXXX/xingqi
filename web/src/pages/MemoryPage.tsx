import { useCallback, useEffect, useState } from "react";
import { errorText } from "../api";
import { StateCard } from "../components/StateCard";
import { stamp } from "../format";
import { useAgentRequest } from "../agentScope";
import type { Item } from "../types";

const RUN_PAGE_SIZE = 20;
const typeLabels: Record<string, string> = {
  profile: "身份",
  preference: "偏好",
  goal: "目标",
  fact: "事实",
  relationship: "关系",
  project: "项目",
};

function localDay(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
}

function memoryDay(item: Item) {
  return /\/daily\/(\d{4}-\d{2}-\d{2})\.md$/.exec(item.file_path || "")?.[1]
    || localDay(item.last_evidence_at);
}

function dayLabel(day: string) {
  if (!day) return "日期未记录";
  const weekday = new Date(`${day}T12:00:00+08:00`).toLocaleDateString("zh-CN", {
    timeZone: "Asia/Shanghai",
    weekday: "long",
  });
  const [year, month, date] = day.split("-").map(Number);
  return `${year}年${month}月${date}日 · ${weekday}`;
}

function runDetails(run: Item): Item {
  try {
    const details = JSON.parse(run.details || "{}");
    return details && !Array.isArray(details) ? details : {};
  } catch {
    return {};
  }
}

function observationStatus(item: Item) {
  if (item.promotion_status === "promoted") return "已沉淀";
  if (item.promotion_status === "deferred") return "待补充证据";
  return "待沉淀";
}

function consolidationSummary(run: Item) {
  if (run.status === "failed") return "本次沉淀未完成";
  if (run.status === "dry_run") return `预览 ${run.candidate_count || 0} 条观察，未写入`;
  if (run.promoted_count || run.superseded_count) {
    return `整理 ${run.candidate_count || 0} 条观察，沉淀 ${run.promoted_count || 0} 条，更新 ${run.superseded_count || 0} 条`;
  }
  return `检查 ${run.candidate_count || 0} 条观察，暂无新的沉淀`;
}

export function MemoryPage({ reloadKey }: { reloadKey: number }) {
  const request = useAgentRequest();
  const [memories, setMemories] = useState<Item[]>([]);
  const [runs, setRuns] = useState<Item[]>([]);
  const [query, setQuery] = useState("");
  const [hasMoreRuns, setHasMoreRuns] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(async (isAlive: () => boolean = () => true) => {
    if (isAlive()) {
      setLoading(true);
      setLoadError("");
    }
    try {
      const [items, recentRuns] = await Promise.all([
        request<Item[]>("/api/memories?tier=episodic"),
        request<Item[]>(`/api/memory-consolidation-runs?limit=${RUN_PAGE_SIZE}`),
      ]);
      if (isAlive()) {
        setMemories(items);
        setRuns(recentRuns);
        setHasMoreRuns(recentRuns.length === RUN_PAGE_SIZE);
      }
    } catch (error) {
      if (isAlive()) setLoadError(errorText(error));
    } finally {
      if (isAlive()) setLoading(false);
    }
  }, [request]);

  useEffect(() => {
    let alive = true;
    void load(() => alive);
    return () => { alive = false; };
  }, [load, reloadKey]);

  async function loadMoreRuns() {
    setLoadingMore(true);
    try {
      const olderRuns = await request<Item[]>(
        `/api/memory-consolidation-runs?limit=${RUN_PAGE_SIZE}&offset=${runs.length}`,
      );
      setRuns((current) => [...current, ...olderRuns]);
      setHasMoreRuns(olderRuns.length === RUN_PAGE_SIZE);
    } catch (error) {
      void window.zhiyuDialogs.alert(errorText(error), "读取日记失败");
    } finally {
      setLoadingMore(false);
    }
  }

  const search = query.trim().toLocaleLowerCase();
  const visibleMemories = search
    ? memories.filter((item) => item.content.toLocaleLowerCase().includes(search))
    : memories;
  const days = new Map<string, { observations: Item[]; runs: Item[] }>();
  for (const item of visibleMemories) {
    const day = memoryDay(item);
    if (!days.has(day)) days.set(day, { observations: [], runs: [] });
    days.get(day)!.observations.push(item);
  }
  if (!search) {
    for (const run of runs) {
      const day = localDay(run.finished_at || run.created_at);
      if (!days.has(day)) days.set(day, { observations: [], runs: [] });
      days.get(day)!.runs.push(run);
    }
  }
  const diary = [...days.entries()].sort(([left], [right]) => right.localeCompare(left));

  return (
    <div className="memory-page diary-page">
      {loading && <div className="loading-line">正在加载日记…</div>}
      {loadError ? (
        <div className="page-content" role="alert">
          <StateCard
            title="日记读取失败"
            description={loadError}
            action={<button className="quiet" onClick={() => void load()}>重试</button>}
          />
        </div>
      ) : (
        <>
          <div className="memory-toolbar">
            <input
              type="search"
              aria-label="搜索每日观察"
              placeholder="搜索每日观察"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <span className="badge">{visibleMemories.length} 条观察</span>
          </div>
          {diary.length ? diary.map(([day, entries]) => (
            <section className="panel diary-day" key={day || "undated"}>
              <header className="diary-day-heading">
                <div>
                  <span className="eyebrow">DAILY NOTES</span>
                  <h2>{dayLabel(day)}</h2>
                </div>
                <span className="diary-day-count">
                  {entries.observations.length} 条观察
                  {entries.runs.length ? ` · ${entries.runs.length} 次沉淀` : ""}
                </span>
              </header>
              {entries.observations.length ? (
                <div className="diary-observations">
                  {entries.observations.map((item) => (
                    <article className="diary-observation" key={item.id}>
                      <div className="diary-entry-meta">
                        <span>{typeLabels[item.type] || item.type}</span>
                        <span>{observationStatus(item)}</span>
                      </div>
                      <p>{item.content}</p>
                      {item.source_content ? (
                        <details className="memory-sources">
                          <summary>查看原话</summary>
                          <p>{item.source_content}</p>
                        </details>
                      ) : null}
                    </article>
                  ))}
                </div>
              ) : null}
              {entries.runs.length ? (
                <div className="diary-consolidations">
                  <h3>记忆沉淀</h3>
                  {entries.runs.map((run) => {
                    const details = runDetails(run);
                    return (
                      <article className="diary-consolidation" key={run.id}>
                        <span className={`status-dot ${run.status === "failed" ? "warning" : ""}`} />
                        <div>
                          <strong>{consolidationSummary(run)}</strong>
                          <small>{stamp(run.finished_at || run.created_at)}</small>
                          {details.rem ? <p>{details.rem}</p> : null}
                          {run.last_error ? <small className="error-text">{run.last_error}</small> : null}
                        </div>
                      </article>
                    );
                  })}
                </div>
              ) : null}
            </section>
          )) : !loading ? (
            <StateCard
              title={search ? "没有匹配的每日观察" : "还没有日记"}
              description={search ? "试试其他关键词。" : "对话中提取的观察与每日沉淀会按日期出现在这里。"}
            />
          ) : null}
          {!search && hasMoreRuns ? (
            <button className="quiet diary-more" disabled={loadingMore} onClick={() => void loadMoreRuns()}>
              {loadingMore ? "正在加载…" : "加载更早的沉淀记录"}
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}
