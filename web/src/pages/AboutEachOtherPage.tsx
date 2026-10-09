import { useCallback, useEffect, useMemo, useState } from "react";
import { errorText, post, request } from "../api";
import { StateCard } from "../components/StateCard";
import type { Item } from "../types";

type FileName = "AGENTS.md" | "SOUL.md" | "BOOTSTRAP.md";
type Profile = { files: Record<FileName, string>; bootstrap_pending: boolean };
type Category = "agent" | "user" | "relationship" | "memories" | "first-meeting";
type Props = {
  reloadKey: number;
  onLoadError: (error: string) => void;
};

const categories: { id: Category; title: string; subtitle: string }[] = [
  { id: "agent", title: "关于星栖", subtitle: "身份与人格" },
  { id: "user", title: "关于你", subtitle: "个人资料与偏好" },
  { id: "relationship", title: "相处方式", subtitle: "规则与边界" },
  { id: "memories", title: "共同记忆", subtitle: "长期记忆" },
  { id: "first-meeting", title: "初次认识", subtitle: "一次性引导" },
];

const fileDetails: Record<FileName, { title: string; description: string }> = {
  "SOUL.md": {
    title: "陪伴人格 · SOUL.md",
    description: "定义星栖的个性、语气、关系感和陪聊边界。",
  },
  "AGENTS.md": {
    title: "对话规则 · AGENTS.md",
    description: "定义星栖如何倾听、使用记忆、回应纠正和处理不确定信息。",
  },
  "BOOTSTRAP.md": {
    title: "初次认识 · BOOTSTRAP.md",
    description: "初次私人对话时，循序了解彼此称呼、聊天偏好与陪伴需求。",
  },
};

const memoryTypeLabels: Record<string, string> = {
  profile: "身份",
  preference: "偏好",
  relationship: "关系",
  fact: "事实",
  goal: "目标",
  project: "项目",
};

function belongsToFile(item: Item, file: string) {
  return (item.file_path || "").endsWith(`/${file}`);
}

export function AboutEachOtherPage({ reloadKey, onLoadError }: Props) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [memories, setMemories] = useState<Item[]>([]);
  const [active, setActive] = useState<Category>("agent");
  const [editingFile, setEditingFile] = useState<FileName>("SOUL.md");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const [currentProfile, currentMemories] = await Promise.all([
      request<Profile>("/api/assistant-profile"),
      request<Item[]>("/api/memories?tier=core"),
    ]);
    setProfile(currentProfile);
    setMemories(currentMemories);
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    void load()
      .catch((error) => {
        if (alive) onLoadError(errorText(error));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [load, onLoadError, reloadKey]);

  const visibleMemories = useMemo(() => {
    if (active === "agent") return memories.filter((item) => belongsToFile(item, "IDENTITY.md"));
    if (active === "user") return memories.filter((item) => belongsToFile(item, "USER.md"));
    if (active === "memories") return memories.filter((item) => belongsToFile(item, "MEMORY.md"));
    return [];
  }, [active, memories]);

  async function saveFile(name: FileName) {
    if (!profile) return;
    setSaving(true);
    setSaved(false);
    try {
      const updated = await request<Profile>(
        `/api/assistant-profile/${encodeURIComponent(name)}`,
        post("PUT", { content: profile.files[name] }),
      );
      setProfile(updated);
      setSaved(true);
    } catch (error) {
      onLoadError(errorText(error));
    } finally {
      setSaving(false);
    }
  }

  async function editMemory(item: Item) {
    const content = await window.zhiyuDialogs.prompt(
      "修改后会同步更新对应的记忆文件。",
      item.content,
      { title: `编辑${memoryTypeLabels[item.type] || "记忆"}` },
    );
    if (content === null || !content.trim()) return;
    try {
      await request(`/api/memories/${encodeURIComponent(item.id)}`, post("PATCH", { content }));
      await load();
    } catch (error) {
      onLoadError(errorText(error));
    }
  }

  async function deleteMemory(item: Item) {
    const confirmed = await window.zhiyuDialogs.confirm(
      "删除后会从对应记忆文件中移除这条内容。",
      "删除记忆",
    );
    if (!confirmed) return;
    try {
      const response = await fetch(`/api/memories/${encodeURIComponent(item.id)}`, {
        method: "DELETE",
        headers: { "X-Zhiyu-Request": "1" },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `请求失败：${response.status}`);
      }
      await load();
    } catch (error) {
      onLoadError(errorText(error));
    }
  }

  async function completeBootstrap() {
    try {
      const updated = await request<Profile>(
        "/api/assistant-profile/bootstrap/complete",
        post("POST"),
      );
      setProfile(updated);
    } catch (error) {
      onLoadError(errorText(error));
    }
  }

  function fileEditor(name: FileName) {
    if (!profile) return null;
    return (
      <section className="panel assistant-profile-editor" key={name}>
        <div className="assistant-profile-editor-heading">
          <div>
            <span className="eyebrow">{name}</span>
            <h2>{fileDetails[name].title}</h2>
            <p>{fileDetails[name].description}</p>
          </div>
          {saved && editingFile === name && <span className="profile-saved" role="status">已保存</span>}
        </div>
        <textarea
          className="assistant-profile-textarea"
          aria-label={fileDetails[name].title}
          value={profile.files[name]}
          maxLength={20000}
          onChange={(event) => {
            setProfile({ ...profile, files: { ...profile.files, [name]: event.target.value } });
            setEditingFile(name);
            setSaved(false);
          }}
        />
        <div className="assistant-profile-actions">
          <small>{profile.files[name].length}/20000 字符</small>
          <button className="primary" disabled={saving} onClick={() => { setEditingFile(name); void saveFile(name); }}>
            {saving && editingFile === name ? "保存中…" : "保存设定"}
          </button>
        </div>
      </section>
    );
  }

  function memorySection(file: "IDENTITY.md" | "USER.md" | "MEMORY.md", emptyText: string) {
    return (
      <section className="panel about-memory-panel">
        <div className="assistant-profile-editor-heading">
          <div>
            <span className="eyebrow">{file}</span>
            <h2>{file === "IDENTITY.md" ? "星栖的身份" : file === "USER.md" ? "你的资料与偏好" : "长期共同记忆"}</h2>
          </div>
          <span className="diary-day-count">{visibleMemories.length} 条</span>
          <button className="danger-button" onClick={() => void (async () => {
            if (!(await window.zhiyuDialogs.confirm("清空默认助手的全部记忆？聊天记录会保留，其他智能体不受影响。", "清空记忆"))) return;
            try { await request("/api/memories/clear", post("POST")); await load(); } catch (error) { onLoadError(errorText(error)); }
          })()}>清空记忆</button>
        </div>
        {visibleMemories.length ? (
          <div className="about-memory-list">
            {visibleMemories.map((item) => (
              <article className="about-memory-entry" key={item.id}>
                <div>
                  <small>{memoryTypeLabels[item.type] || item.type}</small>
                  <p>{item.content}</p>
                </div>
                <div className="about-memory-actions">
                  <button className="quiet" onClick={() => void editMemory(item)}>编辑</button>
                  <button className="quiet" onClick={() => void deleteMemory(item)}>删除</button>
                </div>
              </article>
            ))}
          </div>
        ) : <p className="about-empty">{emptyText}</p>}
      </section>
    );
  }

  return (
    <div className="assistant-profile-page about-each-other-page">
      <article className="panel assistant-profile-intro">
        <span className="eyebrow">ABOUT EACH OTHER</span>
        <h2>关于彼此</h2>
        <p>把星栖是谁、你是谁、我们如何相处，以及共同积累的记忆放在一起。</p>
        <small>工作区文件会在私人对话中按规则加载；日常经历仍记录在「日记」。</small>
      </article>

      <div className="assistant-profile-layout">
        <nav className="assistant-profile-tabs" aria-label="关于彼此分类">
          {categories.map((category) => (
            <button
              key={category.id}
              type="button"
              aria-current={active === category.id ? "page" : undefined}
              className={active === category.id ? "active" : ""}
              onClick={() => {
                setActive(category.id);
                setSaved(false);
              }}
            >
              <strong>{category.title}</strong>
              <small>{category.subtitle}</small>
            </button>
          ))}
        </nav>
        <div className="about-each-other-content">
          {loading ? <div className="loading-line">正在加载…</div> : null}
          {active === "agent" && !loading && (
            <>
              {memorySection("IDENTITY.md", "还没有记录星栖的身份信息。可以在对话中给星栖起名。")}
              {fileEditor("SOUL.md")}
            </>
          )}
          {active === "user" && !loading && memorySection("USER.md", "还没有记录你的资料或偏好。")}
          {active === "relationship" && !loading && (
            <>
              {fileEditor("AGENTS.md")}
              <article className="panel about-file-note">
                <span className="eyebrow">相处原则</span>
                <p>用户明确表达的边界和当前纠正优先；星栖会按这些规则陪聊，也会如实说明记忆不确定的地方。</p>
              </article>
            </>
          )}
          {active === "memories" && !loading && memorySection("MEMORY.md", "长期记忆沉淀后会显示在这里；每日观察仍在「日记」中。")}
          {active === "first-meeting" && !loading && profile && (
            <>
              {fileEditor("BOOTSTRAP.md")}
              <article className="panel bootstrap-status-card">
                <div>
                  <strong>{profile.bootstrap_pending ? "初次认识进行中" : "初次认识已完成"}</strong>
                  <p>{profile.bootstrap_pending ? "星栖会在私人对话中按上方引导自然了解你的称呼和聊天偏好。" : "再次聊天时不会重复进行初次引导。"}</p>
                </div>
                {profile.bootstrap_pending && (
                  <button className="quiet" onClick={() => void completeBootstrap()}>完成初次引导</button>
                )}
              </article>
            </>
          )}
          {!loading && !profile && <StateCard title="关于彼此暂时无法读取" />}
        </div>
      </div>
    </div>
  );
}
