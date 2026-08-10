"use client";

import { useBills, useDamages } from "@/lib/api/hooks";
import { formatDate, formatMoney, formatMoneyRange, humanize } from "@/lib/format";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Note,
  Panel,
  PanelHeader,
  SkeletonRows,
} from "@/components/ui/primitives";
import { useEvidence } from "../evidence";
import type { TabProps } from "../workspace";

function StatusBadge({ status }: { status: string }) {
  if (status === "PENDING") return <Badge tone="warning">Pending</Badge>;
  if (status === "ESTIMATED") return <Badge tone="neutral">Estimated</Badge>;
  return <Badge tone="muted">Known</Badge>;
}

export function BillsTab({ caseId }: TabProps) {
  const bills = useBills(caseId);
  const damages = useDamages(caseId);
  const { show } = useEvidence();

  const futureItems =
    damages.data?.line_items.filter((item) => item.kind === "future_treatment") ?? [];
  const otherDamages =
    damages.data?.line_items.filter((item) => item.kind === "damage_claim") ?? [];

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader
          title="Medical expenses"
          description="Charges of record. Amounts are exact decimals computed by the backend."
        />

        {bills.isLoading ? <SkeletonRows rows={4} /> : null}
        <ErrorState
          error={bills.error ? { message: bills.error.message, status: bills.error.status } : null}
          onRetry={() => bills.refetch()}
        />
        {bills.data && bills.data.length === 0 ? (
          <EmptyState title="No bills recorded" />
        ) : null}

        {bills.data && bills.data.length > 0 ? (
          <table className="w-full text-body">
            <caption className="sr-only">Medical expenses by provider</caption>
            <thead>
              <tr className="border-b border-line text-left text-2xs uppercase tracking-[0.06em] text-ink-faint">
                <th scope="col" className="px-4 py-2 font-medium">
                  Provider
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Description
                </th>
                <th scope="col" className="px-4 py-2 text-right font-medium">
                  Amount
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Status
                </th>
                <th scope="col" className="px-4 py-2 font-medium">
                  Source
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-soft">
              {bills.data.map((bill) => (
                <tr key={bill.id} className="align-top">
                  <td className="px-4 py-2.5 font-medium text-ink">{bill.provider_name}</td>
                  <td className="px-4 py-2.5 text-ink-muted">
                    {bill.description ?? "—"}
                    {bill.billed_on ? (
                      <span className="block text-2xs text-ink-faint">
                        Billed {formatDate(bill.billed_on)}
                      </span>
                    ) : null}
                  </td>
                  <td className="tabular px-4 py-2.5 text-right">
                    {bill.amount === null ? (
                      <span className="text-warn-700">Pending</span>
                    ) : (
                      <span className="font-medium text-ink">{formatMoney(bill.amount)}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={bill.status} />
                  </td>
                  <td className="px-4 py-2.5">
                    {bill.source_document_id ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          show({ kind: "document", documentId: bill.source_document_id! })
                        }
                      >
                        View
                      </Button>
                    ) : (
                      <span className="text-2xs text-ink-faint">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            {damages.data ? (
              <tfoot>
                <tr className="border-t-2 border-line-strong">
                  <th scope="row" colSpan={2} className="px-4 py-2.5 text-left font-medium">
                    Current known medical total
                  </th>
                  <td className="tabular px-4 py-2.5 text-right text-base font-semibold text-ink">
                    {formatMoney(damages.data.current_medical_expenses)}
                  </td>
                  <td colSpan={2} />
                </tr>
              </tfoot>
            ) : null}
          </table>
        ) : null}

        {damages.data && damages.data.pending_bills.length > 0 ? (
          <div className="border-t border-line bg-warn-50/50 px-4 py-2.5">
            <Note>
              <span className="font-medium text-warn-800">
                Pending charges are excluded from the known total.
              </span>{" "}
              A bill with no amount on file is never counted as zero. The known total is a floor
              and will rise once{" "}
              {damages.data.pending_bills.map((bill) => bill.provider_name).join(", ")} bills are
              received.
            </Note>
          </div>
        ) : null}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHeader title="Future medical care" />
          {futureItems.length === 0 ? (
            <div className="px-4 py-4">
              <Note>No future care has been recorded.</Note>
            </div>
          ) : (
            <ul className="divide-y divide-line-soft">
              {futureItems.map((item) => (
                <li key={item.id} className="flex items-start justify-between gap-3 px-4 py-2.5">
                  <div className="min-w-0">
                    <p className="text-body text-ink">{item.description}</p>
                    <p className="text-meta text-ink-faint">
                      {[item.provider_name, item.quantity ? `×${item.quantity}` : null]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  <span className="tabular shrink-0 text-body text-ink-body">
                    {item.amount && item.amount_high
                      ? formatMoneyRange(item.amount, item.amount_high)
                      : formatMoney(item.amount ?? item.amount_high ?? null, "Estimate pending")}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {damages.data ? (
            <div className="flex items-baseline justify-between border-t border-line px-4 py-2.5">
              <span className="text-body font-medium text-ink-body">Future medical expenses</span>
              <span className="tabular text-body font-semibold text-ink">
                {formatMoneyRange(
                  damages.data.future_medical_low,
                  damages.data.future_medical_high,
                )}
              </span>
            </div>
          ) : null}
        </Panel>

        <Panel>
          <PanelHeader title="Other damages" />
          {otherDamages.length === 0 ? (
            <div className="px-4 py-4">
              <Note>No other structured damages recorded.</Note>
            </div>
          ) : (
            <ul className="divide-y divide-line-soft">
              {otherDamages.map((item) => (
                <li key={item.id} className="flex items-start justify-between gap-3 px-4 py-2.5">
                  <div className="min-w-0">
                    <p className="text-body text-ink">{item.description}</p>
                    <p className="text-meta text-ink-faint">{humanize(item.category)}</p>
                  </div>
                  <span className="tabular shrink-0 text-body text-ink-body">
                    {formatMoney(item.amount, "Not quantified")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {damages.data ? (
        <Panel>
          <PanelHeader
            title="Claimed damages"
            description="Every figure below comes from the backend's decimal calculator."
          />
          <dl className="divide-y divide-line-soft">
            {[
              ["Current known medical", formatMoney(damages.data.current_medical_expenses)],
              [
                "Estimated charges not yet finalized",
                formatMoney(damages.data.estimated_bill_total),
              ],
              [
                "Future medical care",
                formatMoneyRange(
                  damages.data.future_medical_low,
                  damages.data.future_medical_high,
                ),
              ],
              ["General damages", formatMoney(damages.data.general_damages)],
              ["Other damages", formatMoney(damages.data.other_damages)],
            ].map(([label, value]) => (
              <div key={label} className="flex items-baseline justify-between px-4 py-2">
                <dt className="text-body text-ink-muted">{label}</dt>
                <dd className="tabular text-body text-ink">{value}</dd>
              </div>
            ))}
            <div className="flex items-baseline justify-between bg-surface-muted px-4 py-2.5">
              <dt className="text-body font-medium text-ink-body">Known claimed damages</dt>
              <dd className="tabular text-base font-semibold text-ink">
                {formatMoneyRange(
                  damages.data.known_claimed_damages_low,
                  damages.data.known_claimed_damages_high,
                )}
              </dd>
            </div>
          </dl>
        </Panel>
      ) : null}
    </div>
  );
}
