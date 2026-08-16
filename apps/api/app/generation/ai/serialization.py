"""Serializing case context so privacy protection cannot destroy its meaning.

A privacy gateway replaces *values*. This module's job is to make sure that
replacing a value can never take a **role** with it.

The failure this exists to prevent happened in production. The context was
prose-shaped:

    Named insured: Harold Whitfield
    Driver at time of collision: Dmitri Kovacs

The detector found a PERSON span that ran past the newline and swallowed the
next field's label — ``Harold Whitfield\\nDriver`` — so what the model received
was:

    Named insured: ⟦PERSON:••••⟧ at time of collision: ⟦PERSON:••••⟧

The word "Driver" was gone, the two lines had collapsed into one, and the model
wrote that the driver *was* the named insured. Deterministic validation caught
it and blocked approval, which is the system working; but the model should never
have been handed a sentence that said that.

The fix is structural, not lexical. Every value is now a leaf of its own record:

    <party id="pty_2" roles="named_insured"><value>"Harold Whitfield"</value></party>
    <party id="pty_3" roles="driver_at_time_of_collision"><value>"Dmitri Kovacs"</value></party>

For a value to consume the next field's identifier it would now have to swallow
a closing quote, a closing tag, a newline, an opening tag, and an ``id``
attribute — and even if it somehow did, the surviving record would be malformed
rather than quietly meaning something else. The role names live outside the
values entirely, so they cannot be tokenized at all.

Two further properties this buys, both of which matter more than the escaping:

* **Identity comes from the domain, not from string comparison.** Parties carry
  their database ids, and a person holding two roles is one record with two
  roles — so "the client is also the driver" and "the client and the driver are
  different people" are different structures, not different sentences. After
  every name becomes an opaque token, that distinction survives intact.
* **Relationships are stated, not implied.** ``<relationship type="different_person">``
  says what the prose note used to say, in a form that has no words for a
  detector to eat.

This is a hardening measure, not a privacy control. The Secure AI Gateway
remains the only thing that decides what is sensitive and what happens to it,
and the deterministic validator remains the thing that decides whether the
resulting prose may be approved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from xml.sax.saxutils import escape

from ...domain.enums import PartyRole
from ...domain.money import format_money
from ..context import DemandContext, format_date

#: Stable machine-readable identifier for each party role. These are part of the
#: prompt contract: they never change with wording, and they never contain a
#: value, so no privacy transformation can touch them.
ROLE_IDS: dict[PartyRole, str] = {
    PartyRole.CLIENT: "client",
    PartyRole.INSURED: "named_insured",
    PartyRole.DRIVER: "driver_at_time_of_collision",
    PartyRole.VEHICLE_OWNER: "vehicle_owner",
    PartyRole.ADJUSTER: "adjuster",
    PartyRole.ATTORNEY: "attorney_of_record",
    PartyRole.WITNESS: "witness",
}

#: What each role means, in words that contain no case data. The model reads
#: these once and can then interpret opaque tokens correctly: a token is
#: meaningless, but "the person driving at the time of the collision" is not.
ROLE_DEFINITIONS: dict[str, str] = {
    "client": "The person this firm represents; the claimant.",
    "named_insured": "The person named as the insured on the policy at issue.",
    "driver_at_time_of_collision": "The person driving the at-fault vehicle when the collision occurred.",
    "vehicle_owner": "The registered owner of a vehicle involved.",
    "adjuster": "The carrier's claims handler.",
    "attorney_of_record": "Counsel of record for the client.",
    "witness": "A witness to the collision.",
}

#: Role pairs whose confusion changes what the letter legally asserts. Each one
#: gets an explicit relationship record so the distinction cannot be inferred —
#: or mis-inferred — from names that may no longer be readable.
NOTABLE_PAIRS: tuple[tuple[str, str], ...] = (
    ("client", "named_insured"),
    ("client", "driver_at_time_of_collision"),
    ("named_insured", "driver_at_time_of_collision"),
    ("named_insured", "vehicle_owner"),
    ("driver_at_time_of_collision", "vehicle_owner"),
)


def _text(value: object) -> str:
    """One line of escaped text. Newlines inside a value stay inside it."""
    if isinstance(value, (date, datetime)):
        rendered = format_date(value)
    else:
        rendered = str(value)
    # Normalize line endings so a CRLF source cannot produce records that differ
    # only by an invisible character.
    rendered = rendered.replace("\r\n", "\n").replace("\r", "\n").strip()
    return escape(rendered, {'"': "&quot;"})


def _fact(field: str, value: object) -> str:
    """One field record. The identifier is an attribute; the value is a leaf.

    The quotes inside ``<value>`` are defence in depth — the tags are what
    actually bounds the value, and the quotes make an over-long span visibly
    wrong rather than silently plausible.
    """
    return f'<fact field="{field}"><value>"{_text(value)}"</value></fact>'


@dataclass(frozen=True)
class _PartyRecord:
    id: str
    roles: tuple[str, ...]
    name: str


def _party_records(ctx: DemandContext) -> list[_PartyRecord]:
    """One record per party, carrying every role that party holds.

    A person with two roles is one record with two roles. That is the whole
    identity model: it comes from the party's database id, never from comparing
    names, so it survives pseudonymization untouched.
    """
    records: list[_PartyRecord] = []
    for party in ctx.parties:
        roles = tuple(ROLE_IDS[role] for role in party.roles if role in ROLE_IDS)
        if not roles:
            continue
        records.append(_PartyRecord(id=party.id, roles=roles, name=party.full_name))
    return records


def _relationships(records: list[_PartyRecord]) -> list[str]:
    """Explicit same/different-person statements for the pairs that matter."""
    holder: dict[str, list[_PartyRecord]] = {}
    for record in records:
        for role in record.roles:
            holder.setdefault(role, []).append(record)

    lines: list[str] = []
    for left, right in NOTABLE_PAIRS:
        first = holder.get(left)
        second = holder.get(right)
        if not first or not second:
            continue
        a, b = first[0], second[0]
        kind = "same_person" if a.id == b.id else "different_person"
        lines.append(
            f'<relationship type="{kind}" a="{a.id}" b="{b.id}" '
            f'a_role="{left}" b_role="{right}"/>'
        )
    return lines


def build_case_context(ctx: DemandContext) -> str:
    """The structured case context handed to the model.

    Compact by construction: one record per line, no repeated values, and refs
    by party id rather than by repeating a name. Nothing is omitted that the
    prose form carried — the same facts are present, in a shape a value
    replacement cannot rearrange.
    """
    parties = _party_records(ctx)
    used_roles = sorted({role for record in parties for role in record.roles})

    lines: list[str] = ["<case_context>"]

    if used_roles:
        lines.append("<role_definitions>")
        lines.extend(
            f'<role id="{role}">{escape(ROLE_DEFINITIONS[role])}</role>' for role in used_roles
        )
        lines.append("</role_definitions>")

    if parties:
        lines.append("<parties>")
        for record in parties:
            roles = " ".join(record.roles)
            lines.append(
                f'<party id="{record.id}" roles="{roles}">'
                f'<value>"{_text(record.name)}"</value></party>'
            )
        lines.append("</parties>")

        relationships = _relationships(parties)
        if relationships:
            lines.append("<relationships>")
            lines.extend(relationships)
            lines.append("</relationships>")

    client = ctx.client
    if client is None:
        # A case may carry the client's name without a party record for them.
        # The prose form printed it, so this must too: dropping it to keep the
        # structure tidy would be omitting a fact, and the letter needs the
        # name. It is a case field rather than a party, and says so.
        display_name = getattr(getattr(ctx, "case", None), "client_display_name", None)
        if display_name:
            lines.append("<case>")
            lines.append(_fact("client_display_name", display_name))
            lines.append("</case>")
    if ctx.claim:
        lines.append("<claim>")
        lines.append(_fact("claim_number", ctx.claim.claim_number))
        lines.append(_fact("date_of_loss", ctx.claim.date_of_loss))
        if client is not None:
            # The claimant by reference, not by repeating the name.
            lines.append(f'<ref field="claimant" party="{client.id}"/>')
        if ctx.claim.carrier:
            lines.append(_fact("insurance_carrier", ctx.claim.carrier.name))
            if ctx.claim.carrier.adjuster_name:
                lines.append(_fact("claim_adjuster", ctx.claim.carrier.adjuster_name))
        lines.append("</claim>")

    if ctx.accident:
        lines.append("<accident>")
        lines.append(_fact("collision_date", ctx.accident.occurred_on))
        if ctx.accident.location:
            lines.append(_fact("collision_location", ctx.accident.location))
        if ctx.accident.description:
            lines.append(_fact("collision_description", ctx.accident.description))
        lines.append("</accident>")

    if ctx.timeline:
        lines.append("<treatment_timeline>")
        for index, entry in enumerate(ctx.timeline, start=1):
            record = [f'<event id="ev{index}">', _fact("treatment_date", entry.entry_date)]
            if entry.provider:
                record.append(_fact("treatment_provider", entry.provider))
            record.append(_fact("treatment_description", entry.title))
            if entry.detail:
                record.append(_fact("treatment_detail", entry.detail))
            if client is not None:
                record.append(f'<ref field="patient" party="{client.id}"/>')
            record.append("</event>")
            lines.append("".join(record))
        lines.append("</treatment_timeline>")

    if ctx.imaging_findings:
        lines.append("<imaging_studies>")
        for index, imaging in enumerate(ctx.imaging_findings, start=1):
            record = [f'<study id="img{index}">', _fact("imaging_date", imaging.study_date)]
            if imaging.provider is not None:
                record.append(_fact("imaging_provider", imaging.provider.name))
            record.append(_fact("imaging_modality", imaging.modality))
            if imaging.body_region:
                record.append(_fact("imaging_body_region", imaging.body_region))
            if imaging.level:
                record.append(_fact("imaging_level", imaging.level))
            record.append(_fact("imaging_finding", imaging.finding))
            if imaging.measurement:
                record.append(_fact("imaging_measurement", imaging.measurement))
            if client is not None:
                record.append(f'<ref field="patient" party="{client.id}"/>')
            record.append("</study>")
            lines.append("".join(record))
        lines.append("</imaging_studies>")

    # Money is computed by the calculator and inserted by the template. It
    # appears here for reference only, and the instruction that it must not be
    # restated travels as an attribute rather than as prose a span could eat.
    lines.append("<damages_reference restate=\"forbidden\">")
    lines.append(
        _fact("current_medical_expenses", format_money(ctx.damages.current_medical_expenses))
    )
    lines.append("</damages_reference>")

    lines.append("</case_context>")
    return "\n".join(lines)
