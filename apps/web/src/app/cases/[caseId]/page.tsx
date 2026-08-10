import { Suspense } from "react";

import { CaseWorkspace } from "@/components/case/workspace";

export default async function CasePage({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await params;
  return (
    <Suspense fallback={<div className="p-6 text-sm text-slate-500">Loading case…</div>}>
      <CaseWorkspace caseId={caseId} />
    </Suspense>
  );
}
