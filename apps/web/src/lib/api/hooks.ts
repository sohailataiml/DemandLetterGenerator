"use client";

/** TanStack Query bindings. Components never call fetch directly. */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { ApiError, apiFetch } from "./client";
import type {
  Accident,
  AuditEvent,
  Bill,
  CaseRecord,
  CaseSummary,
  Claim,
  Damages,
  Demand,
  Fact,
  FactStatus,
  Party,
  Provider,
  SettlementTerms,
  SourceDocument,
  SourceDocumentDetail,
  TimelineEntry,
  ValidationIssue,
  Vehicle,
} from "./types";

export const queryKeys = {
  caseSummaries: ["case-summaries"] as const,
  case: (id: string) => ["case", id] as const,
  claim: (id: string) => ["case", id, "claim"] as const,
  accident: (id: string) => ["case", id, "accident"] as const,
  vehicles: (id: string) => ["case", id, "vehicles"] as const,
  settlement: (id: string) => ["case", id, "settlement-terms"] as const,
  parties: (id: string) => ["case", id, "parties"] as const,
  providers: (id: string) => ["case", id, "providers"] as const,
  timeline: (id: string) => ["case", id, "timeline"] as const,
  bills: (id: string) => ["case", id, "bills"] as const,
  damages: (id: string) => ["case", id, "damages"] as const,
  facts: (id: string, status?: FactStatus) => ["case", id, "facts", status ?? "all"] as const,
  documents: (id: string) => ["case", id, "documents"] as const,
  document: (documentId: string) => ["document", documentId] as const,
  demands: (id: string) => ["case", id, "demands"] as const,
  demand: (demandId: string) => ["demand", demandId] as const,
  caseAudit: (id: string) => ["case", id, "audit"] as const,
  demandAudit: (demandId: string) => ["demand", demandId, "audit"] as const,
};

/** Endpoints that legitimately 404 when the record has not been entered yet. */
function optionalResource<T>(
  key: readonly unknown[],
  path: string,
  enabled = true,
): UseQueryOptions<T | null, ApiError> {
  return {
    queryKey: key,
    enabled,
    queryFn: async () => {
      try {
        return await apiFetch<T>(path);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  };
}

export function useCaseSummaries() {
  return useQuery<CaseSummary[], ApiError>({
    queryKey: queryKeys.caseSummaries,
    queryFn: () => apiFetch<CaseSummary[]>("/v1/case-summaries"),
  });
}

export function useCase(caseId: string) {
  return useQuery<CaseRecord, ApiError>({
    queryKey: queryKeys.case(caseId),
    queryFn: () => apiFetch<CaseRecord>(`/v1/cases/${caseId}`),
    enabled: Boolean(caseId),
  });
}

export function useClaim(caseId: string) {
  return useQuery(optionalResource<Claim>(queryKeys.claim(caseId), `/v1/cases/${caseId}/claim`, Boolean(caseId)));
}

export function useAccident(caseId: string) {
  return useQuery(
    optionalResource<Accident>(queryKeys.accident(caseId), `/v1/cases/${caseId}/accident`, Boolean(caseId)),
  );
}

export function useSettlementTerms(caseId: string) {
  return useQuery(
    optionalResource<SettlementTerms>(
      queryKeys.settlement(caseId),
      `/v1/cases/${caseId}/settlement-terms`,
      Boolean(caseId),
    ),
  );
}

export function useVehicles(caseId: string) {
  return useQuery<Vehicle[], ApiError>({
    queryKey: queryKeys.vehicles(caseId),
    queryFn: () => apiFetch<Vehicle[]>(`/v1/cases/${caseId}/vehicles`),
    enabled: Boolean(caseId),
  });
}

export function useParties(caseId: string) {
  return useQuery<Party[], ApiError>({
    queryKey: queryKeys.parties(caseId),
    queryFn: () => apiFetch<Party[]>(`/v1/cases/${caseId}/parties`),
    enabled: Boolean(caseId),
  });
}

export function useProviders(caseId: string) {
  return useQuery<Provider[], ApiError>({
    queryKey: queryKeys.providers(caseId),
    queryFn: () => apiFetch<Provider[]>(`/v1/cases/${caseId}/providers`),
    enabled: Boolean(caseId),
  });
}

export function useTimeline(caseId: string) {
  return useQuery<TimelineEntry[], ApiError>({
    queryKey: queryKeys.timeline(caseId),
    queryFn: () => apiFetch<TimelineEntry[]>(`/v1/cases/${caseId}/medical-timeline`),
    enabled: Boolean(caseId),
  });
}

export function useBills(caseId: string) {
  return useQuery<Bill[], ApiError>({
    queryKey: queryKeys.bills(caseId),
    queryFn: () => apiFetch<Bill[]>(`/v1/cases/${caseId}/bills`),
    enabled: Boolean(caseId),
  });
}

export function useDamages(caseId: string) {
  return useQuery<Damages, ApiError>({
    queryKey: queryKeys.damages(caseId),
    queryFn: () => apiFetch<Damages>(`/v1/cases/${caseId}/damages`),
    enabled: Boolean(caseId),
  });
}

export function useFacts(caseId: string, status?: FactStatus) {
  const query = status ? `?status=${status}` : "";
  return useQuery<Fact[], ApiError>({
    queryKey: queryKeys.facts(caseId, status),
    queryFn: () => apiFetch<Fact[]>(`/v1/cases/${caseId}/facts${query}`),
    enabled: Boolean(caseId),
  });
}

export function useDocuments(caseId: string) {
  return useQuery<SourceDocument[], ApiError>({
    queryKey: queryKeys.documents(caseId),
    queryFn: () => apiFetch<SourceDocument[]>(`/v1/cases/${caseId}/documents`),
    enabled: Boolean(caseId),
  });
}

export function useDocument(documentId: string | null) {
  return useQuery<SourceDocumentDetail, ApiError>({
    queryKey: queryKeys.document(documentId ?? "none"),
    queryFn: () => apiFetch<SourceDocumentDetail>(`/v1/documents/${documentId}`),
    enabled: Boolean(documentId),
  });
}

export function useDemands(caseId: string) {
  return useQuery<Demand[], ApiError>({
    queryKey: queryKeys.demands(caseId),
    queryFn: () => apiFetch<Demand[]>(`/v1/cases/${caseId}/demands`),
    enabled: Boolean(caseId),
  });
}

export function useDemand(demandId: string | null) {
  return useQuery<Demand, ApiError>({
    queryKey: queryKeys.demand(demandId ?? "none"),
    queryFn: () => apiFetch<Demand>(`/v1/demands/${demandId}`),
    enabled: Boolean(demandId),
  });
}

export function useCaseAudit(caseId: string) {
  return useQuery<AuditEvent[], ApiError>({
    queryKey: queryKeys.caseAudit(caseId),
    queryFn: () => apiFetch<AuditEvent[]>(`/v1/cases/${caseId}/audit?limit=500`),
    enabled: Boolean(caseId),
  });
}

// ------------------------------------------------------------------ mutations

function useCaseInvalidation(caseId: string) {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ["case", caseId] });
    queryClient.invalidateQueries({ queryKey: queryKeys.caseSummaries });
    queryClient.invalidateQueries({ queryKey: ["demand"] });
  };
}

export function useVerifyFact(caseId: string) {
  const invalidate = useCaseInvalidation(caseId);
  return useMutation<Fact, ApiError, string>({
    mutationFn: (factId) => apiFetch<Fact>(`/v1/facts/${factId}/verify`, { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useRejectFact(caseId: string) {
  const invalidate = useCaseInvalidation(caseId);
  return useMutation<Fact, ApiError, { factId: string; reason: string }>({
    mutationFn: ({ factId, reason }) =>
      apiFetch<Fact>(`/v1/facts/${factId}/reject`, { method: "POST", body: { reason } }),
    onSuccess: invalidate,
  });
}

export interface SupersedeInput {
  factId: string;
  summary: string;
  reason: string;
  fact_type: string;
  value: Record<string, unknown>;
  sources: { document_id: string; page_number: number | null; excerpt: string | null }[];
}

export function useSupersedeFact(caseId: string) {
  const invalidate = useCaseInvalidation(caseId);
  return useMutation<Fact, ApiError, SupersedeInput>({
    mutationFn: ({ factId, ...body }) =>
      apiFetch<Fact>(`/v1/facts/${factId}/supersede`, { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useCreateDemand(caseId: string) {
  const invalidate = useCaseInvalidation(caseId);
  return useMutation<Demand, ApiError, { letter_date?: string }>({
    mutationFn: (body) =>
      apiFetch<Demand>(`/v1/cases/${caseId}/demands`, { method: "POST", body }),
    onSuccess: invalidate,
  });
}

export function useGenerateDemand(caseId: string) {
  const invalidate = useCaseInvalidation(caseId);
  return useMutation<Demand, ApiError, { demandId: string; regenerate_sections?: string[] }>({
    mutationFn: ({ demandId, regenerate_sections }) =>
      apiFetch<Demand>(`/v1/demands/${demandId}/generate`, {
        method: "POST",
        body: { regenerate_sections: regenerate_sections ?? null },
      }),
    onSuccess: invalidate,
  });
}

export function useValidateDemand(caseId: string) {
  const invalidate = useCaseInvalidation(caseId);
  return useMutation<ValidationIssue[], ApiError, string>({
    mutationFn: (demandId) =>
      apiFetch<ValidationIssue[]>(`/v1/demands/${demandId}/validate`, { method: "POST" }),
    onSuccess: invalidate,
  });
}

export function useApproveDemand(caseId: string) {
  const invalidate = useCaseInvalidation(caseId);
  return useMutation<Demand, ApiError, { demandId: string; acknowledgement: string }>({
    mutationFn: ({ demandId, acknowledgement }) =>
      apiFetch<Demand>(`/v1/demands/${demandId}/approve`, {
        method: "POST",
        body: { acknowledgement },
      }),
    onSuccess: invalidate,
  });
}

export function useEditSection(caseId: string) {
  const invalidate = useCaseInvalidation(caseId);
  return useMutation<Demand, ApiError, { demandId: string; key: string; body: string }>({
    mutationFn: ({ demandId, key, body }) =>
      apiFetch<Demand>(`/v1/demands/${demandId}/sections/${key}`, {
        method: "PATCH",
        body: { body },
      }),
    onSuccess: invalidate,
  });
}
