import { useContext, useEffect, useState } from "react";
import { errorText, post } from "../api";
import { StateCard } from "../components/StateCard";
import { stamp } from "../format";
import { AgentScope, useAgentRequest } from "../agentScope";
import type { Item } from "../types";

type Props = {
  reloadKey: number;
  onLoadError: (error: string) => void;
  act: (action: () => Promise<unknown>, refresh?: boolean) => Promise<void>;
  installSkill: () => Promise<void>;
};

export function SkillsPage({ reloadKey, onLoadError, act, installSkill }: Props) {
  const request = useAgentRequest();
  const characterId = useContext(AgentScope);
  const [skills, setSkills] = useState<Item[]>([]);
  const [trash, setTrash] = useState<Item[]>([]);
  const [pageLoading, setPageLoading] = useState(true);
  const dialog = window.zhiyuDialogs;
  useEffect(() => {
    let alive = true;
    setPageLoading(true);
    void Promise.all([
      request<Item[]>("/api/skills"),
      request<Item[]>("/api/skills/trash"),
    ])
      .then(([list, old]) => {
        if (!alive) return;
        setSkills(list);
        setTrash(old);
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
  }, [onLoadError, reloadKey, request]);
  return (
    <div className="page-content">
      {pageLoading && <div className="loading-line">正在加载…</div>}
      <div className="notice">
        {characterId ? "选择要关联给当前智能体的 Skill。启用和停用只影响当前智能体。" : "Skill 内容按需读取；安装不会执行其中代码或自动安装依赖。"}
      </div>
      {skills.length ? (
        <div className="manage-list">
          {skills.map((item) => (
            <article className="manage-card" key={item.name}>
              <div className="manage-card-head">
                <div>
                  <span className="eyebrow">
                    {item.source_type || "本地"} {item.revision || ""}
                  </span>
                  <h2>{item.name}</h2>
                </div>
                <span
                  className={`status-pill ${item.enabled && item.available ? "good" : "muted-pill"}`}
                >
                  {item.enabled
                    ? item.available
                      ? "已启用"
                      : "缺少依赖"
                    : "已停用"}
                </span>
              </div>
              <p>{item.description || item.error || "暂无描述"}</p>
              <p className="meta-line">
                工具依赖：{(item.required_tools || []).join("、") || "无"} ·
                命令依赖：{(item.missing_bins || []).join("、") || "满足"}
                {item.modified ? " · 本地内容有修改" : ""}
              </p>
              <div className="card-actions">
                {(item.managed || characterId) && (
                  <>
                    <button
                      className="quiet"
                      onClick={() =>
                        void act(async () => {
                          await request(
                            `/api/skills/${encodeURIComponent(item.name)}/enabled`,
                            post("PUT", { enabled: !item.enabled }),
                          );
                          setSkills(await request<Item[]>("/api/skills"));
                        })
                      }
                    >
                      {item.enabled ? "停用" : "启用"}
                    </button>
                    {!characterId && <button
                      className="quiet"
                      onClick={() =>
                        void act(async () => {
                          if (
                            item.modified &&
                            !(await dialog.confirm(
                              "此 Skill 有本地修改，应用更新可能覆盖当前文件。仍要继续预览吗？",
                              "Skill 有本地修改",
                            ))
                          )
                            return;
                          const ref = await dialog.prompt(
                            "目标分支或 Tag（留空使用原来源）",
                            "",
                            { title: "检查 Skill 更新" },
                          );
                          if (ref === null) return;
                          const body = { ref: ref || null };
                          const preview = await request<Item>(
                            `/api/skills/${encodeURIComponent(item.name)}/update-preview`,
                            post("POST", body),
                          );
                          if (!preview.changed) {
                            dialog.notify("已是最新版本");
                            return;
                          }
                          if (
                            !(await dialog.confirm(
                              `更新 ${item.name}？\n${(preview.changed_files || []).slice(0, 20).join("\n")}`,
                              "确认更新",
                            ))
                          )
                            return;
                          await request(
                            `/api/skills/${encodeURIComponent(item.name)}/update`,
                            post("POST", body),
                          );
                          setSkills(await request<Item[]>("/api/skills"));
                        })
                      }
                    >
                      检查更新
                    </button>}
                    <button
                      className="danger-button"
                      onClick={() =>
                        void act(async () => {
                          if (
                            !(await dialog.confirm(
                              characterId ? `移除 ${item.name} 与当前智能体的关联？` : `将 ${item.name} 移入回收站？`,
                            ))
                          )
                            return;
                          await request(
                            `/api/skills/${encodeURIComponent(item.name)}`,
                            post("DELETE"),
                          );
                          setSkills(await request<Item[]>("/api/skills"));
                          setTrash(await request<Item[]>("/api/skills/trash"));
                        })
                      }
                    >
                      {characterId ? "移除关联" : "移入回收站"}
                    </button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        !pageLoading && (
          <StateCard
            title="还没有可用 Skill"
            description="安装本地 Skill 文件夹或 HTTPS Git 仓库。"
            action={
              <button className="primary" onClick={() => void installSkill()}>
                安装 Skill
              </button>
            }
          />
        )
      )}
      {!characterId && <article className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">TRASH</span>
            <h2>回收站</h2>
          </div>
        </div>
        {trash.map((item) => (
          <div className="list-row" key={item.name}>
            <span className="row-main">{item.name}</span>
            <small>
              {item.source_type} · {stamp(item.trashed_at)}
            </small>
            <button
              className="quiet"
              onClick={() =>
                void act(async () => {
                  await request(
                    `/api/skills/${encodeURIComponent(item.name)}/restore`,
                    post("POST"),
                  );
                  setSkills(await request<Item[]>("/api/skills"));
                  setTrash(await request<Item[]>("/api/skills/trash"));
                })
              }
            >
              恢复
            </button>
          </div>
        ))}
        {trash.length === 0 && <p className="muted">回收站为空</p>}
      </article>}
    </div>
  );
}
