import { useEffect, useState } from "react";
import { errorText, post, request } from "../api";
import type { Item } from "../types";

type Props = {
  reloadKey: number;
  onLoadError: (error: string) => void;
  act: (action: () => Promise<unknown>, refresh?: boolean) => Promise<void>;
};

export function ChannelsPage({ reloadKey, onLoadError, act }: Props) {
  const [qq, setQq] = useState<Item | null>(null);
  const [channels, setChannels] = useState<Item[]>([]);
  const [groups, setGroups] = useState<Item[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setPageLoading(true);
    void Promise.all([
      request<Item>("/api/qq/config"),
      request<Item[]>("/api/channels"),
      request<Item[]>("/api/qq/groups"),
    ])
      .then(([config, list, groupList]) => {
        if (!alive) return;
        setQq(config);
        setChannels(list);
        setGroups(groupList);
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
            <span className="eyebrow">CONNECTION STATUS</span>
            <h2>NapCat / OneBot</h2>
          </div>
          <span
            className={`status-pill ${channels.find((item) => item.channel === "qq")?.status === "connected" ? "good" : "warn"}`}
          >
            {channels.find((item) => item.channel === "qq")?.status || "未连接"}
          </span>
        </div>
        <p>
          {channels.find((item) => item.channel === "qq")?.last_error ||
            channels.find((item) => item.channel === "qq")?.ws_url ||
            "尚未配置连接"}
        </p>
      </article>
      <form
        className="panel form-panel"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void act(async () => {
            await request(
              "/api/qq/config",
              post("PUT", {
                endpoint: form.get("endpoint"),
                owner_user_id: form.get("owner") || null,
                token: form.get("token") || null,
              }),
            );
            setQq(await request<Item>("/api/qq/config"));
          });
        }}
      >
        <div className="panel-heading">
          <div>
            <span className="eyebrow">CONNECTION</span>
            <h2>连接配置</h2>
          </div>
        </div>
        <label>
          NapCat 反向 WebSocket 地址
          <input
            name="endpoint"
            required
            defaultValue={qq?.endpoint || "ws://127.0.0.1:6199/ws"}
          />
        </label>
        <label>
          主人 QQ 号
          <input
            name="owner"
            inputMode="numeric"
            defaultValue={qq?.owner_user_id || ""}
          />
        </label>
        <label>
          Access Token
          <input
            name="token"
            type="password"
            autoComplete="new-password"
            placeholder={
              qq?.token_readable ? "已保存；留空保持不变" : "留空则不设置"
            }
          />
        </label>
        <p className="form-hint">Token 保存在本机密钥存储，不会回显。</p>
        <div className="button-row">
          <button className="primary">保存配置</button>
          <button
            type="button"
            className="quiet"
            onClick={() =>
              void act(async () => {
                await request("/api/qq/start", post("POST"));
                setChannels(await request<Item[]>("/api/channels"));
              })
            }
          >
            启动连接
          </button>
          <button
            type="button"
            className="quiet"
            onClick={() =>
              void act(async () => {
                await request("/api/qq/stop", post("POST"));
                setChannels(await request<Item[]>("/api/channels"));
              })
            }
          >
            停止
          </button>
        </div>
      </form>
      <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">GROUP ACCESS</span>
            <h2>群聊白名单</h2>
          </div>
        </div>
        <form
          className="inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const groupId = String(form.get("group") || "");
            void act(async () => {
              await request(
                `/api/qq/groups/${encodeURIComponent(groupId)}`,
                post("PUT", {
                  enabled: true,
                  require_mention: form.get("mention") === "on",
                }),
              );
              setGroups(await request<Item[]>("/api/qq/groups"));
            });
          }}
        >
          <input name="group" placeholder="QQ群号" required />
          <label className="check">
            <input name="mention" type="checkbox" defaultChecked />
            必须 @ 知语
          </label>
          <button className="quiet">允许此群</button>
        </form>
        <div className="simple-list">
          {groups.map((group) => (
            <div className="list-row" key={group.group_id}>
              <span className="row-main">{group.group_id}</span>
              <small>
                {group.enabled ? "已允许" : "已禁用"} ·{" "}
                {group.require_mention ? "需 @" : "无需 @"}
              </small>
              <button
                className="text-button"
                onClick={() =>
                  void act(async () => {
                    await request(
                      `/api/qq/groups/${encodeURIComponent(group.group_id)}`,
                      post("PUT", { enabled: false }),
                    );
                    setGroups(await request<Item[]>("/api/qq/groups"));
                  }, false)
                }
              >
                移除
              </button>
            </div>
          ))}
          {groups.length === 0 && (
            <p className="muted">当前没有群聊白名单。私聊不受影响。</p>
          )}
        </div>
      </article>
    </div>
  );
}
