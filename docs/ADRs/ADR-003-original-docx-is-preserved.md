# ADR-003 — The original DOCX is preserved, not reconstructed

**Status:** accepted (supersedes the original `docx_renderer` as the primary path)

## Context

The assignment is "match the template exactly in structure, formatting and
layout". The original implementation built a new `docx.Document()` on every
render — Calibri 11, one-inch margins, a generated footer. It could never match
a firm's letterhead, because no template was ever read.

Reconstructing a template from a description is lossy in a way that is hard to
bound: numbering definitions, theme fonts, tab stops, cell shading, section
breaks, embedded logos. Each one is a thing to notice missing after the letter
has gone out.

## Decision

Generation opens the uploaded `.docx` and edits only the elements a
`DynamicSlot` points at. Everything else keeps the exact XML it arrived with.
Block and row slots clone *their own source element* per output item, so
repeated content inherits the formatting of the sample the attorney wrote.

Fidelity is verified by re-analyzing the output and comparing manifests, and
that comparison runs during validation so a failure gates approval.

## Consequences

- No DRAFT watermark on the template path; stamping one would be exactly the
  mutation this prevents. Drafts are marked by filename and by the UI.
- A template using a slot with no resolver fails loudly (`TEMPLATE_002`) rather
  than producing a half-filled letter.
- Part digests are canonicalized (C14N) before hashing, because Word, lxml and
  python-docx serialize equivalent XML differently and a validator that reports
  false mutations gets ignored.

## Rejected

**Raw ZIP/string surgery on `document.xml`.** Faster to write, and it breaks the
moment Word splits a placeholder across runs — which it does routinely. Working
on the parsed tree handles run splitting correctly and cannot produce malformed
OOXML.
