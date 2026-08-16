"""Structural integrity of the context sent to the model.

These tests exist because of a real failure on the deployed demo. The context
was prose:

    Named insured: Harold Whitfield
    Driver at time of collision: Dmitri Kovacs

A detected PERSON span crossed the newline and took the word "Driver" with it,
so the model received ``Named insured: ⟦PERSON:••••⟧ at time of collision:
⟦PERSON:••••⟧`` and drafted a sentence making the driver the named insured.
Deterministic validation blocked approval, which is the safety net working —
but the model should never have been handed that sentence.

What is asserted here is one property, from several angles: **replacing values
must not change the structure.** Strip the values from the original and strip
the tokens from the protected version, and the two skeletons must be identical.

Every name below is invented.
"""

from __future__ import annotations

import re

import pytest

from app.domain.enums import PartyRole
from app.domain.models import Party, PartyRoleAssignment
from app.generation.ai.serialization import ROLE_IDS, build_case_context

# --------------------------------------------------------------- test doubles


class _Damages:
    current_medical_expenses = 0


class _Carrier:
    def __init__(self, name: str, adjuster_name: str | None = None) -> None:
        self.name = name
        self.adjuster_name = adjuster_name


class _Claim:
    def __init__(self, claim_number, date_of_loss, carrier=None) -> None:
        self.claim_number = claim_number
        self.date_of_loss = date_of_loss
        self.carrier = carrier


class _Accident:
    def __init__(self, occurred_on, location=None, description=None) -> None:
        self.occurred_on = occurred_on
        self.location = location
        self.description = description


class _Event:
    def __init__(self, entry_date, title, provider=None, detail=None) -> None:
        self.entry_date = entry_date
        self.title = title
        self.provider = provider
        self.detail = detail


class _Provider:
    def __init__(self, name: str) -> None:
        self.name = name


class _Imaging:
    def __init__(self, study_date, provider=None, **kwargs) -> None:
        self.study_date = study_date
        self.provider = provider
        self.modality = kwargs.get("modality", "MRI")
        self.body_region = kwargs.get("body_region")
        self.level = kwargs.get("level")
        self.finding = kwargs.get("finding", "disc protrusion")
        self.measurement = kwargs.get("measurement")


class _Context:
    """The attribute surface ``build_case_context`` reads, and nothing else."""

    def __init__(
        self, parties=(), claim=None, accident=None, timeline=(), imaging=(), case=None
    ) -> None:
        self.parties = list(parties)
        self.case = case
        self.claim = claim
        self.accident = accident
        self.timeline = list(timeline)
        self.imaging_findings = list(imaging)
        self.damages = _Damages()

    @property
    def client(self):
        return next((p for p in self.parties if p.has_role(PartyRole.CLIENT)), None)


def party(identifier: str, name: str, *roles: PartyRole) -> Party:
    """An unsaved party. Identity is its id, exactly as in the database."""
    return Party(
        id=identifier,
        full_name=name,
        role_assignments=[PartyRoleAssignment(role=role.value) for role in roles],
    )


CLIENT = PartyRole.CLIENT
INSURED = PartyRole.INSURED
DRIVER = PartyRole.DRIVER
OWNER = PartyRole.VEHICLE_OWNER

#: The three people from the deployed failure.
THREE_PARTIES = (
    party("pty_1", "Elena Marquez", CLIENT),
    party("pty_2", "Harold Whitfield", INSURED),
    party("pty_3", "Dmitri Kovacs", DRIVER),
)


# ------------------------------------------------------------------ helpers

_VALUE = re.compile(r'<value>"[^"]*"</value>')
_TOKEN_VALUE = re.compile(r"<value>(?:\"?)(?:⟦[^⟧]*⟧|PERSON_\d+|[A-Z_]+_\d+)(?:\"?)</value>")


def skeleton(text: str) -> str:
    """The structure with every value — real or tokenized — removed."""
    without_tokens = _TOKEN_VALUE.sub("<value/>", text)
    return _VALUE.sub("<value/>", without_tokens)


def tokenize(text: str, names: dict[str, str]) -> str:
    """A well-behaved privacy transformation: replace exactly the values."""
    for name, token in names.items():
        text = text.replace(name, token)
    return text


def greedy_person_spans(text: str, names: dict[str, str]) -> str:
    """A *badly* behaved one, modelled on what actually happened.

    The detector's span ran past the end of the name, across a newline, and took
    the following capitalised word with it. Reproducing the over-capture — not
    Presidio — is the point: this is the adversary the serialization has to
    survive.
    """
    for name, token in names.items():
        text = re.sub(rf"{re.escape(name)}(\r?\n[A-Z][a-z]+)?", token, text)
    return text


def legacy_prose(parties) -> str:
    """The format that failed in production, kept only as the control case."""
    lines = []
    for record in parties:
        if record.has_role(CLIENT):
            lines.append(f"Client: {record.full_name}")
        elif record.has_role(INSURED):
            lines.append(f"Named insured: {record.full_name}")
        elif record.has_role(DRIVER):
            lines.append(f"Driver at time of collision: {record.full_name}")
    return "\n".join(lines)


# ------------------------------------------------- the deployed failure case


def test_three_people_serialize_as_three_records_with_stable_role_ids():
    context = build_case_context(_Context(parties=THREE_PARTIES))

    for role_id in ("client", "named_insured", "driver_at_time_of_collision"):
        assert f'roles="{role_id}"' in context, role_id

    # Each value is independently bounded: its own tags, its own quotes.
    assert '<party id="pty_1" roles="client"><value>"Elena Marquez"</value></party>' in context
    assert (
        '<party id="pty_2" roles="named_insured"><value>"Harold Whitfield"</value></party>'
        in context
    )
    assert (
        '<party id="pty_3" roles="driver_at_time_of_collision">'
        '<value>"Dmitri Kovacs"</value></party>' in context
    )


def test_the_insured_and_the_driver_are_stated_to_be_different_people():
    context = build_case_context(_Context(parties=THREE_PARTIES))

    assert (
        '<relationship type="different_person" a="pty_2" b="pty_3" '
        'a_role="named_insured" b_role="driver_at_time_of_collision"/>' in context
    )


def test_the_over_capturing_span_that_broke_production_cannot_break_this():
    """The regression. Same greedy detector, both formats, different outcomes."""
    names = {
        "Elena Marquez": "⟦PERSON:••••⟧",
        "Harold Whitfield": "⟦PERSON:••••⟧",
        "Dmitri Kovacs": "⟦PERSON:••••⟧",
    }

    # The control: the old prose loses the word "Driver" exactly as it did live.
    damaged = greedy_person_spans(legacy_prose(THREE_PARTIES), names)
    assert "Driver at time of collision" not in damaged
    assert "at time of collision: ⟦PERSON:••••⟧" in damaged

    # The fix: the same span cannot reach past a value's closing quote and tag.
    protected = greedy_person_spans(build_case_context(_Context(parties=THREE_PARTIES)), names)
    assert 'roles="named_insured"' in protected
    assert 'roles="driver_at_time_of_collision"' in protected
    assert '<relationship type="different_person" a="pty_2" b="pty_3"' in protected
    assert skeleton(protected) == skeleton(build_case_context(_Context(parties=THREE_PARTIES)))


def test_each_role_still_maps_to_its_own_opaque_value():
    """PERSON_A → client, PERSON_B → named_insured, PERSON_C → driver."""
    protected = tokenize(
        build_case_context(_Context(parties=THREE_PARTIES)),
        {"Elena Marquez": "PERSON_16", "Harold Whitfield": "PERSON_17", "Dmitri Kovacs": "PERSON_18"},
    )

    assert '<party id="pty_1" roles="client"><value>"PERSON_16"</value></party>' in protected
    assert '<party id="pty_2" roles="named_insured"><value>"PERSON_17"</value></party>' in protected
    assert (
        '<party id="pty_3" roles="driver_at_time_of_collision">'
        '<value>"PERSON_18"</value></party>' in protected
    )
    # And the roles are never inside a value, so they cannot be tokenized at all.
    assert "PERSON_17 at time of collision" not in protected


# ------------------------------------------------- the skeleton invariant


ANONYMOUS = {
    "Elena Marquez": "⟦PERSON:••••⟧",
    "Harold Whitfield": "⟦PERSON:••••⟧",
    "Dmitri Kovacs": "⟦PERSON:••••⟧",
    "Cascade Imaging Center": "⟦ORGANIZATION:••••⟧",
    "Willamette Spine Care": "⟦ORGANIZATION:••••⟧",
    "R. Okonkwo": "⟦PERSON:••••⟧",
    "Cascade Mutual Assurance": "⟦ORGANIZATION:••••⟧",
    "SE Division St and 39th Ave, Portland, OR": "⟦LOCATION:••••⟧",
    "August 3, 2026": "⟦DATE_TIME:••••⟧",
    "March 2, 2026": "⟦DATE_TIME:••••⟧",
}


@pytest.mark.parametrize(
    ("name", "context"),
    [
        (
            "client / named insured / driver",
            _Context(parties=THREE_PARTIES),
        ),
        (
            "patient / medical provider",
            _Context(
                parties=(party("pty_1", "Elena Marquez", CLIENT),),
                timeline=(_Event("2026-03-02", "Initial evaluation", provider="Willamette Spine Care"),),
            ),
        ),
        (
            "claimant / adjuster",
            _Context(
                parties=(party("pty_1", "Elena Marquez", CLIENT),),
                claim=_Claim("CLM-77401992", "2026-03-02", _Carrier("Cascade Mutual Assurance", "R. Okonkwo")),
            ),
        ),
        (
            "provider / treatment date",
            _Context(
                parties=(party("pty_1", "Elena Marquez", CLIENT),),
                timeline=(_Event("August 3, 2026", "Follow-up", provider="Cascade Imaging Center"),),
            ),
        ),
        (
            "provider / bill amount",
            _Context(
                parties=(party("pty_1", "Elena Marquez", CLIENT),),
                imaging=(_Imaging("August 3, 2026", provider=_Provider("Cascade Imaging Center")),),
            ),
        ),
        (
            "accident location / date of loss",
            _Context(
                parties=(party("pty_1", "Elena Marquez", CLIENT),),
                claim=_Claim("CLM-77401992", "March 2, 2026"),
                accident=_Accident("March 2, 2026", location="SE Division St and 39th Ave, Portland, OR"),
            ),
        ),
    ],
)
def test_the_structural_skeleton_survives_protection(name, context):
    original = build_case_context(context)

    assert skeleton(tokenize(original, ANONYMOUS)) == skeleton(original), name
    assert skeleton(greedy_person_spans(original, ANONYMOUS)) == skeleton(original), name


# ------------------------------------------------------- adversarial adjacency


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (party("pty_2", "Harold Whitfield", INSURED), party("pty_3", "Dmitri Kovacs", DRIVER)),
        (party("pty_1", "Elena Marquez", CLIENT), party("pty_2", "Harold Whitfield", INSURED)),
        (party("pty_1", "Elena Marquez", CLIENT), party("pty_4", "Elena Marquez", OWNER)),
    ],
)
def test_adjacent_pii_heavy_records_keep_their_own_identifiers(first, second):
    context = build_case_context(_Context(parties=(first, second)))
    protected = greedy_person_spans(context, {first.full_name: "⟦PERSON:••••⟧", second.full_name: "⟦PERSON:••••⟧"})

    for record in (first, second):
        role_id = ROLE_IDS[record.roles[0]]
        assert f'<party id="{record.id}" roles="{role_id}">' in protected


def test_a_provider_and_a_patient_on_adjacent_lines_stay_distinct():
    context = _Context(
        parties=(party("pty_1", "Elena Marquez", CLIENT),),
        timeline=(_Event("2026-03-02", "MRI", provider="Cascade Imaging Center"),),
    )
    protected = greedy_person_spans(build_case_context(context), ANONYMOUS)

    assert 'field="treatment_provider"' in protected
    assert '<ref field="patient" party="pty_1"/>' in protected


def test_a_driver_next_to_a_collision_location_stays_distinct():
    context = _Context(
        parties=(party("pty_3", "Dmitri Kovacs", DRIVER),),
        accident=_Accident("March 2, 2026", location="SE Division St and 39th Ave, Portland, OR"),
    )
    protected = greedy_person_spans(build_case_context(context), ANONYMOUS)

    assert 'roles="driver_at_time_of_collision"' in protected
    assert 'field="collision_location"' in protected


# ------------------------------------------------------------ awkward values


@pytest.mark.parametrize(
    "name",
    [
        "Mary-Jane O'Sullivan",
        "Renée Étienne-Bouchard",
        "Владимир Ковач",
        'Ann "Annie" Shaw',
        "李 明",
        "Jean-Luc de la Cruz-Núñez",
    ],
)
def test_awkward_names_stay_inside_one_bounded_record(name):
    context = build_case_context(_Context(parties=(party("pty_9", name, INSURED),)))

    # Exactly one party record, and the structure around it is intact.
    assert context.count('<party id="pty_9"') == 1
    assert context.count("</party>") == 1
    assert '<party id="pty_9" roles="named_insured"><value>"' in context
    assert '"</value></party>' in context
    # A quote inside a name is escaped rather than closing the value early.
    assert '"</value></party>' in context and context.count("<parties>") == 1


def test_crlf_and_lf_produce_the_same_records():
    address = "1200 Alder St\r\nSuite 400\r\nPortland, OR 97205"
    crlf = build_case_context(
        _Context(
            parties=(party("pty_1", "Elena Marquez", CLIENT),),
            accident=_Accident("March 2, 2026", location=address),
        )
    )
    lf = build_case_context(
        _Context(
            parties=(party("pty_1", "Elena Marquez", CLIENT),),
            accident=_Accident("March 2, 2026", location=address.replace("\r\n", "\n")),
        )
    )

    assert crlf == lf
    assert "\r" not in crlf


def test_a_multiline_address_does_not_leak_into_the_next_record():
    context = build_case_context(
        _Context(
            parties=(party("pty_1", "Elena Marquez", CLIENT),),
            accident=_Accident(
                "March 2, 2026",
                location="1200 Alder St\nSuite 400\nPortland, OR 97205",
                description="Left-turn collision.",
            ),
        )
    )

    assert 'field="collision_location"' in context
    assert 'field="collision_description"' in context
    # The address sits inside its own value; the next field's identifier is
    # outside it and on its own line.
    location_line = next(line for line in context.splitlines() if "Suite 400" in line)
    assert 'field="collision_description"' not in location_line


def test_missing_optional_values_omit_records_rather_than_emitting_blanks():
    context = build_case_context(
        _Context(
            parties=(party("pty_1", "Elena Marquez", CLIENT),),
            accident=_Accident("March 2, 2026"),
        )
    )

    assert 'field="collision_date"' in context
    assert 'field="collision_location"' not in context
    assert 'field="collision_description"' not in context
    assert '<value>""</value>' not in context


# ------------------------------------------------------------------ identity


def test_one_person_holding_two_roles_is_one_record_and_says_so():
    both = party("pty_1", "Elena Marquez", CLIENT, DRIVER)
    context = build_case_context(_Context(parties=(both,)))

    assert '<party id="pty_1" roles="client driver_at_time_of_collision">' in context
    assert (
        '<relationship type="same_person" a="pty_1" b="pty_1" '
        'a_role="client" b_role="driver_at_time_of_collision"/>' in context
    )
    assert "different_person" not in context


def test_two_people_with_the_same_name_remain_two_parties():
    """Identity comes from the party id. Matching strings prove nothing."""
    context = build_case_context(
        _Context(
            parties=(
                party("pty_1", "Alex Romero", INSURED),
                party("pty_2", "Alex Romero", DRIVER),
            )
        )
    )

    assert '<party id="pty_1" roles="named_insured">' in context
    assert '<party id="pty_2" roles="driver_at_time_of_collision">' in context
    assert '<relationship type="different_person" a="pty_1" b="pty_2"' in context


def test_the_same_person_stays_the_same_person_after_tokenization():
    both = party("pty_1", "Elena Marquez", CLIENT, DRIVER)
    protected = tokenize(
        build_case_context(_Context(parties=(both,))), {"Elena Marquez": "PERSON_16"}
    )

    assert '<party id="pty_1" roles="client driver_at_time_of_collision">' in protected
    assert '<relationship type="same_person" a="pty_1" b="pty_1"' in protected


class _Case:
    def __init__(self, client_display_name: str) -> None:
        self.client_display_name = client_display_name


def test_a_case_without_a_client_party_still_carries_the_client_name():
    """The prose form printed it from the case record; dropping it would be
    omitting a fact, not simplifying one."""
    context = build_case_context(_Context(case=_Case("Elena Marquez")))

    assert '<fact field="client_display_name"><value>"Elena Marquez"</value></fact>' in context
    # It is a case field, not an invented party: no fake identity is minted.
    assert "<party " not in context


def test_role_identifiers_never_appear_inside_a_value():
    """The property the whole design rests on."""
    context = build_case_context(
        _Context(
            parties=THREE_PARTIES,
            claim=_Claim("CLM-77401992", "March 2, 2026", _Carrier("Cascade Mutual Assurance")),
            accident=_Accident("March 2, 2026", location="SE Division St, Portland, OR"),
        )
    )

    for value in re.findall(r"<value>\"([^\"]*)\"</value>", context):
        for role_id in ROLE_IDS.values():
            assert role_id not in value
        assert "<" not in value and ">" not in value


def test_no_case_data_appears_in_the_role_definitions():
    context = build_case_context(_Context(parties=THREE_PARTIES))
    definitions = context.split("</role_definitions>")[0]

    for record in THREE_PARTIES:
        assert record.full_name not in definitions
