import { useEffect, useState } from "react";
import { errorText, post, request } from "../api";
import { stamp } from "../format";
import type { Item } from "../types";

type Props = {
  reloadKey: number;
  onLoadError: (error: string) => void;
  act: (action: () => Promise<unknown>, refresh?: boolean) => Promise<void>;
};

export function DiagnosticsPage({ reloadKey, onLoadError, act }: Props) {
  const [events, setEvents] = useState<Item[]>([]);
  const [deliveries, setDeliveries] = useState<Item[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const dialog = window.zhiyuDialogs;
  useEffect(() => {
    let alive = true;
    setPageLoading(true);
    void Promise.all([
      request<Item[]>("/api/channel-events?limit=100"),
      request<Item[]>("/api/channel-deliveries?limit=100"),
    ])
      .then(([inbound, outbound]) => {
        if (!alive) return;
        setEvents(inbound);
        setDeliveries(outbound);
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
  }, [onLoadError, reloadKey]);
  return (
    <div className="page-content">
      {pageLoading && <div className="loading-line">正在加载…</div>}
      <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">INBOUND · 最近 100 条</span>
            <h2>渠道事件</h2>
          </div>
        </div>
        {events.map((item) => (
          <div className="table-row" key={item.id}>
            <div>
              <strong>{item.status}</strong>
              <small>{item.id}</small>
            </div>
            <small>{stamp(item.received_at)}</small>
            <small>{item.last_error || "—"}</small>
            {["failed", "pending"].includes(item.status) ? (
              <button
                className="quiet"
                onClick={() =>
                  void act(async () => {
                    await request(
                      `/api/channel-events/${encodeURIComponent(item.id)}/replay`,
                      post("POST"),
                    );
                    setEvents(
                      await request<Item[]>("/api/channel-events?limit=100"),
                    );
                  }, false)
                }
              >
                重放
              </button>
            ) : null}
          </div>
        ))}
        {events.length === 0 && !pageLoading && (
          <p className="muted">暂无事件记录</p>
        )}
      </article>
      <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">OUTBOUND · 最近 100 条</span>
            <h2>消息投递</h2>
          </div>
        </div>
        {deliveries.map((item) => (
          <div className="table-row" key={item.id}>
            <div>
              <strong>{item.status}</strong>
              <small>{item.id}</small>
            </div>
            <small>{item.provider_message_id || "无外部消息 ID"}</small>
            <small>{item.error || "—"}</small>
            {["failed", "unknown"].includes(item.status) ? (
              <button
                className="quiet"
                onClick={() =>
                  void act(async () => {
                    const unknown = item.status === "unknown";
                    if (
                      unknown &&
                      !(await dialog.confirm(
                        "发送结果未知，QQ 可能已经收到。仍要再次发送吗？",
                        "确认再次投递",
                      ))
                    )
                      return;
                    await request(
                      `/api/channel-deliveries/${encodeURIComponent(item.id)}/retry`,
                      post("POST", { allow_unknown: unknown }),
                    );
                    setDeliveries(
                      await request<Item[]>(
                        "/api/channel-deliveries?limit=100",
                      ),
                    );
                  }, false)
                }
              >
                {item.status === "unknown" ? "确认重试" : "重试"}
              </button>
            ) : null}
          </div>
        ))}
        {deliveries.length === 0 && !pageLoading && (
          <p className="muted">暂无投递记录</p>
        )}
      </article>
    </div>
  );
}
