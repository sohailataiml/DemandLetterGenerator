"""Prompt construction for grounded narrative drafting.

The contract is the same for every section: use only the supplied verified
facts, never infer, preserve names and numbers exactly, and say so plainly when
the evidence is not sufficient to draft. Whatever the model returns is still
re-checked against the fact store afterwards — the prompt is a first line of
defence, not the guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass

PROMPT_VERSION = "narrative_v1"

SYSTEM_PROMPT = """\
You are drafting one section of a personal injury demand letter for attorney review.

Use ONLY the provided verified facts and structured case data.
Do not infer diagnoses, dates, costs, liability, or treatment.
Do not introduce facts not present in the context.
Preserve names and numeric values exactly as given; never round, restate, or \
recompute a dollar amount or a date.
Do not state a total, a sum, or any arithmetic result — totals are computed \
elsewhere and inserted by the system.
If the evidence is insufficient, set "insufficient_evidence" to true, explain \
what is missing, and leave the text empty.

Return the fact IDs you actually relied on in "used_fact_ids". A fact ID you \
did not use must not appear there.
Write in the voice of plaintiff's counsel: factual, measured, and free of \
speculation about the reader's motives.
"""

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "section": {"type": "string"},
        "text": {"type": "string"},
        "used_fact_ids": {"type": "array", "items": {"type": "string"}},
        "insufficient_evidence": {"type": "boolean"},
        "missing": {"type": "string"},
    },
    "required": ["section", "text", "used_fact_ids", "insufficient_evidence", "missing"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    instruction: str
    fact_types: tuple[str, ...]


SECTION_SPECS: dict[str, SectionSpec] = {
    "liability": SectionSpec(
        key="liability",
        title="Liability",
        instruction=(
            "Describe how the collision occurred and why the insured driver is responsible, "
            "using only the accident record and liability facts supplied. State the roles of "
            "the named insured and the driver separately if they are different people. Do not "
            "characterise the evidence as conclusive beyond what the facts state."
        ),
        fact_types=("liability",),
    ),
    "medical_summary": SectionSpec(
        key="medical_summary",
        title="Medical History and Treatment",
        instruction=(
            "Summarise the course of treatment in chronological order from the timeline and "
            "verified treatment facts. Name each provider exactly as given. Do not add "
            "diagnoses, and do not state any total cost."
        ),
        fact_types=("treatment_event", "diagnosis"),
    ),
    "imaging_summary": SectionSpec(
        key="imaging_summary",
        title="Diagnostic Imaging Findings",
        instruction=(
            "Report the imaging findings exactly as recorded, including spinal level and "
            "measurement where present. Do not interpret findings beyond the report language "
            "and do not assert causation that is not in the facts."
        ),
        fact_types=("imaging_finding",),
    ),
    "pain_and_suffering": SectionSpec(
        key="pain_and_suffering",
        title="Pain, Suffering, and Inconvenience",
        instruction=(
            "Describe the effect of the injuries on daily life using only verified functional "
            "limitation facts. Do not estimate a monetary value and do not describe limitations "
            "that are not documented."
        ),
        fact_types=("functional_limitation", "diagnosis", "treatment_event"),
    ),
}


def build_user_prompt(
    *, spec: SectionSpec, context_block: str, facts_block: str
) -> str:
    return (
        f"Section to draft: {spec.key} — {spec.title}\n\n"
        f"Instruction:\n{spec.instruction}\n\n"
        f"Structured case data (authoritative):\n{context_block}\n\n"
        f"Verified facts available for this section:\n{facts_block}\n\n"
        "Draft the section now. Return JSON matching the required schema."
    )
