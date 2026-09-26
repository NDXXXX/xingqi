export default function Placeholder({ title }: { title: string }) {
  return (
    <section className="flex h-full items-center justify-center">
      <p className="text-sm text-neutral-500">{title} — 将在后续 Phase 实现。</p>
    </section>
  )
}
