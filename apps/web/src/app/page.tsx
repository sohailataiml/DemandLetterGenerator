import { CaseList } from "@/components/case-list";

export default function HomePage() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-6xl items-baseline justify-between gap-6 px-6 py-5">
          <div className="min-w-0">
            <h1 className="text-section font-semibold tracking-tight text-ink">
              Demand Letter Review
            </h1>
            <p className="mt-1 max-w-2xl text-meta leading-5 text-ink-muted">
              Letters are assembled from attorney-verified facts. Totals and dates are computed by
              the backend; drafting assistance never sets a figure.
            </p>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-6">
        <CaseList />
      </main>
    </div>
  );
}
