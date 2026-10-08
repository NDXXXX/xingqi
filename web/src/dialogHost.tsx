import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Button, Modal } from "@heroui/react";
import "./dialogs.css";

type DialogRequest = {
  kind: "prompt" | "confirm" | "alert" | "form";
  title: string;
  message: string;
  initial?: string;
  placeholder?: string;
  submitText?: string;
  inputType?: "text" | "password";
  fields?: FormField[];
  resolve: (value: DialogResult) => void;
};

type DialogResult = string | boolean | Record<string, string | boolean> | null;

type FormField = {
  name: string;
  label: string;
  type?: "text" | "password" | "url" | "number" | "textarea" | "select" | "checkbox";
  value?: string | boolean;
  placeholder?: string;
  description?: string;
  required?: boolean;
  options?: { label: string; value: string }[];
  dependsOn?: { name: string; value: string };
};

declare global {
  interface Window {
    zhiyuDialogsReady: Promise<void>;
    zhiyuDialogs: {
      prompt: (message: string, initial?: string, options?: { title?: string; placeholder?: string; inputType?: "text" | "password" }) => Promise<string | null>;
      form: (title: string, message: string, fields: FormField[], submitText?: string) => Promise<Record<string, string | boolean> | null>;
      confirm: (message: string, title?: string) => Promise<boolean>;
      alert: (message: string, title?: string) => Promise<void>;
      notify: (message: string, kind?: "success" | "error") => void;
    };
  }
}

let resolveDialogsReady: () => void;
window.zhiyuDialogsReady = new Promise((resolve) => { resolveDialogsReady = resolve; });

function DialogHost() {
  const [active, setActive] = useState<DialogRequest | null>(null);
  const [value, setValue] = useState("");
  const [formValues, setFormValues] = useState<Record<string, string | boolean>>({});
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState<{ text: string; kind: "success" | "error" } | null>(null);

  useEffect(() => {
    let queue = Promise.resolve();
    const request = (item: Omit<DialogRequest, "resolve">) => new Promise<DialogResult>((resolve) => {
      queue = queue.then(() => new Promise<void>((done) => {
        setValue(item.initial || "");
        setFormValues(Object.fromEntries((item.fields || []).map((field) => [field.name, field.value ?? ""])));
        setFormError("");
        setActive({ ...item, resolve: (result) => { resolve(result); done(); } });
      }));
    });
    window.zhiyuDialogs = {
      prompt: async (message, initial = "", options = {}) => {
        const result = await request({ kind: "prompt", title: options.title || "填写信息", message, initial, placeholder: options.placeholder, inputType: options.inputType });
        return typeof result === "string" ? result : null;
      },
      form: async (title, message, fields, submitText = "保存") => {
        const result = await request({ kind: "form", title, message, fields, submitText });
        return result && typeof result === "object" ? result : null;
      },
      confirm: async (message, title = "请确认") => (await request({ kind: "confirm", title, message })) === true,
      alert: async (message, title = "操作结果") => { await request({ kind: "alert", title, message }); },
      notify: (message, kind = "success") => {
        setNotice({ text: message, kind });
        window.setTimeout(() => setNotice((current) => current?.text === message ? null : current), 3200);
      },
    };
    resolveDialogsReady();
    return () => { delete (window as Partial<Window>).zhiyuDialogs; };
  }, []);

  function finish(result: DialogResult) {
    active?.resolve(result);
    setActive(null);
    setValue("");
    setFormValues({});
    setFormError("");
  }

  return <>
    <Modal>
      <Modal.Backdrop isOpen={Boolean(active)} onOpenChange={(open) => { if (!open) finish(null); }} variant="blur">
        <Modal.Container placement="center" size="sm">
          <Modal.Dialog aria-label={active?.title || "星栖对话框"} className="zh-modal">
            {({ close }) => <>
              <Modal.Header className="zh-modal-header">
                <div><span className="zh-modal-eyebrow">ZHIYU · LOCAL AGENT</span><Modal.Heading>{active?.title}</Modal.Heading></div>
                <Modal.CloseTrigger onPress={() => { finish(null); close(); }} aria-label="关闭">×</Modal.CloseTrigger>
              </Modal.Header>
              <Modal.Body className="zh-modal-body">
                <p>{active?.message}</p>
                {active?.kind === "prompt" && <input autoFocus aria-label={active.message} className="zh-modal-input" type={active.inputType || "text"} placeholder={active.placeholder} value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); finish(value); } }} />}
                {active?.kind === "form" && <div className="zh-form-fields">{(active.fields || []).filter((field) => !field.dependsOn || formValues[field.dependsOn.name] === field.dependsOn.value).map((field) => <label className={`zh-form-field ${field.type === "checkbox" ? "toggle" : ""}`} key={field.name}>
                  {field.type === "checkbox" ? <><input type="checkbox" checked={Boolean(formValues[field.name])} onChange={(event) => setFormValues((current) => ({ ...current, [field.name]: event.target.checked }))} /><span><strong>{field.label}</strong>{field.description && <small>{field.description}</small>}</span></> : <><span className="zh-form-label">{field.label}{field.required && <i> *</i>}</span>{field.type === "select" ? <select required={field.required} value={String(formValues[field.name] ?? "")} onChange={(event) => setFormValues((current) => ({ ...current, [field.name]: event.target.value }))}>{(field.options || []).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : field.type === "textarea" ? <textarea required={field.required} rows={3} placeholder={field.placeholder} value={String(formValues[field.name] ?? "")} onChange={(event) => setFormValues((current) => ({ ...current, [field.name]: event.target.value }))} /> : <input required={field.required} type={field.type || "text"} placeholder={field.placeholder} value={String(formValues[field.name] ?? "")} onChange={(event) => setFormValues((current) => ({ ...current, [field.name]: event.target.value }))} />}{field.description && <small>{field.description}</small>}</>}
                </label>)}</div>}
                {formError && <p className="zh-form-error" role="alert">{formError}</p>}
              </Modal.Body>
              <Modal.Footer className="zh-modal-footer">
                {active?.kind !== "alert" && <Button variant="tertiary" onPress={() => finish(null)}>取消</Button>}
                <Button variant="primary" onPress={() => {
                  if (active?.kind === "form") {
                    const missing = (active.fields || []).find((field) => field.required && (!field.dependsOn || formValues[field.dependsOn.name] === field.dependsOn.value) && !String(formValues[field.name] ?? "").trim());
                    if (missing) { setFormError(`请填写“${missing.label}”。`); return; }
                    finish(formValues);
                    return;
                  }
                  finish(active?.kind === "confirm" || active?.kind === "alert" ? true : value);
                }}>
                  {active?.kind === "confirm" ? "确认" : active?.kind === "alert" ? "知道了" : active?.kind === "form" ? active.submitText : "继续"}
                </Button>
              </Modal.Footer>
            </>}
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
    {notice && <div role="status" className={`zh-toast ${notice.kind}`}>{notice.text}</div>}
  </>;
}

const rootNode = document.createElement("div");
rootNode.id = "zhiyu-react-overlay";
document.body.append(rootNode);
createRoot(rootNode).render(<DialogHost />);
