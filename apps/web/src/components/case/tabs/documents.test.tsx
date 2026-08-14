import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DocumentsTab } from "./documents";
import { EvidenceProvider } from "../evidence";
import {
  CASE_ID,
  demand,
  documentDetail,
  facts,
  letterTemplate,
  letterTemplateDetail,
  uploadLimits,
} from "@/test/fixtures";
import { mockApi, mockXhrUpload, renderWithProviders, type RouteTable } from "@/test/utils";

const goToTab = vi.fn();

/** Only the routes this tab actually requests, so a stray call is visible. */
function routes(overrides: RouteTable = {}): RouteTable {
  return {
    "/v1/upload-limits": { body: uploadLimits },
    [`/v1/cases/${CASE_ID}/templates`]: { body: [] },
    [`/v1/cases/${CASE_ID}/documents`]: { body: [] },
    [`/v1/cases/${CASE_ID}/facts`]: { body: [] },
    [`/v1/cases/${CASE_ID}/demands`]: { body: [] },
    "/v1/templates/tmpl_1": { body: letterTemplateDetail },
    ...overrides,
  };
}

function renderTab() {
  return renderWithProviders(
    <EvidenceProvider>
      <DocumentsTab
        caseId={CASE_ID}
        demand={undefined}
        goToTab={goToTab}
        focusedSection={null}
      />
    </EvidenceProvider>,
  );
}

function docxFile(name = "demand-template.docx"): File {
  return new File(["PK"], name, {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
}

describe("documents tab", () => {
  it("keeps the template and the case materials in separate, differently worded sections", async () => {
    mockApi(routes());
    renderTab();

    expect(await screen.findByText("Demand letter template")).toBeInTheDocument();
    // Also named in the trust-model panel, hence more than one match.
    expect(screen.getAllByText("Case materials").length).toBeGreaterThan(0);

    // The two roles are stated, not left for the attorney to infer.
    expect(
      screen.getByText(/controls the final letter's structure and formatting/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/require attorney verification before they can be used/i),
    ).toBeInTheDocument();

    // Two distinct pickers, not one generic uploader with a type dropdown.
    expect(await screen.findByLabelText("Drop the Word template here")).toBeInTheDocument();
    expect(screen.getByLabelText("Drop case documents here")).toBeInTheDocument();
  });

  it("guides a brand-new case through the three steps in order", async () => {
    mockApi(routes());
    renderTab();

    expect(await screen.findByText("Start here")).toBeInTheDocument();
    expect(screen.getByText("Demand template")).toBeInTheDocument();
    expect(screen.getByText("Verify facts")).toBeInTheDocument();
    expect(screen.getByText("Waiting for documents")).toBeInTheDocument();
  });

  it("advertises only the formats the backend told it it accepts", async () => {
    mockApi(routes());
    renderTab();

    const templatePicker = await screen.findByLabelText("Drop the Word template here");
    expect(templatePicker).toHaveAttribute("accept", ".docx");

    const materialsPicker = screen.getByLabelText("Drop case documents here");
    expect(materialsPicker).toHaveAttribute("accept", ".docx,.pdf,.txt");
    expect(materialsPicker).toHaveAttribute("multiple");
  });

  it("uploads a chosen .docx template and shows what the analyzer found", async () => {
    const user = userEvent.setup();
    let templates: unknown[] = [];
    mockApi(
      routes({
        [`/v1/cases/${CASE_ID}/templates`]: () => ({ body: templates }),
      }),
    );
    const uploads = mockXhrUpload(() => {
      templates = [letterTemplate];
      return { status: 201, body: letterTemplateDetail };
    });

    renderTab();
    await screen.findByLabelText("Drop the Word template here");

    await user.upload(screen.getByLabelText("Drop the Word template here"), docxFile());

    await waitFor(() => expect(uploads).toHaveLength(1));
    expect(uploads[0].url).toContain(`/v1/cases/${CASE_ID}/templates`);
    expect(uploads[0].headers["X-User-Role"]).toBe("attorney");

    expect(await screen.findByText("demand-template.docx")).toBeInTheDocument();
    // Real numbers from the response, not placeholders.
    expect(await screen.findByText("16")).toBeInTheDocument();
    expect(screen.getByText("Analyzed")).toBeInTheDocument();
  });

  it("refuses a dropped file that is not a Word document, without contacting the server", async () => {
    mockApi(routes());
    const uploads = mockXhrUpload(() => ({ status: 201, body: letterTemplateDetail }));

    renderTab();
    await screen.findByLabelText("Drop the Word template here");

    // Drag-and-drop is the path that gets past the picker's accept filter, so
    // it is the path where this guard has to hold.
    fireEvent.drop(screen.getByRole("button", { name: /Drop the Word template here/ }), {
      dataTransfer: { files: [new File(["%PDF-"], "records.pdf", { type: "application/pdf" })] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(".pdf is not accepted");
    expect(uploads).toHaveLength(0);
  });

  it("uploads several case materials at once and lists each one's state", async () => {
    const user = userEvent.setup();
    mockApi(routes());
    const uploads = mockXhrUpload((call) => ({
      status: 201,
      body: { ...documentDetail, id: `doc_${call.fileNames[0]}`, status: "extracted" },
    }));

    renderTab();
    await screen.findByLabelText("Drop case documents here");

    await user.upload(screen.getByLabelText("Drop case documents here"), [
      new File(["report"], "police-report.pdf", { type: "application/pdf" }),
      new File(["records"], "medical-records.pdf", { type: "application/pdf" }),
    ]);

    await waitFor(() => expect(uploads).toHaveLength(2));
    const queued = await screen.findByTestId("upload-police-report.pdf");
    expect(within(queued).getByText("Ready for extraction")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("upload-medical-records.pdf")).getByText("Ready for extraction"),
    ).toBeInTheDocument();
  });

  it("offers a retry after a transient failure, and it succeeds", async () => {
    const user = userEvent.setup();
    mockApi(routes());
    let attempt = 0;
    mockXhrUpload(() => {
      attempt += 1;
      return attempt === 1
        ? { status: 503, body: { detail: "storage backend unavailable" } }
        : { status: 201, body: { ...documentDetail, status: "extracted" } };
    });

    renderTab();
    await screen.findByLabelText("Drop case documents here");
    await user.upload(
      screen.getByLabelText("Drop case documents here"),
      new File(["x"], "records.pdf", { type: "application/pdf" }),
    );

    const row = await screen.findByTestId("upload-records.pdf");
    expect(await within(row).findByText(/storage backend unavailable/)).toBeInTheDocument();

    await user.click(within(row).getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(within(row).getByText("Ready for extraction")).toBeInTheDocument(),
    );
  });

  it("states a rejection in the server's own words and does not offer a pointless retry", async () => {
    const user = userEvent.setup();
    mockApi(routes());
    mockXhrUpload(() => ({
      status: 400,
      body: { detail: "malware signature detected (EICAR test file)" },
    }));

    renderTab();
    await screen.findByLabelText("Drop case documents here");
    await user.upload(
      screen.getByLabelText("Drop case documents here"),
      new File(["x"], "suspect.pdf", { type: "application/pdf" }),
    );

    const row = await screen.findByTestId("upload-suspect.pdf");
    expect(await within(row).findByText(/malware signature detected/)).toBeInTheDocument();
    // Resending the same bytes cannot change a verdict on those bytes.
    expect(within(row).queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("marks a document whose text could not be read as stored but not ready", async () => {
    const user = userEvent.setup();
    mockApi(routes());
    mockXhrUpload(() => ({
      status: 201,
      body: { ...documentDetail, status: "needs_ocr" },
    }));

    renderTab();
    await screen.findByLabelText("Drop case documents here");
    await user.upload(
      screen.getByLabelText("Drop case documents here"),
      new File(["scan"], "scan.pdf", { type: "application/pdf" }),
    );

    const row = await screen.findByTestId("upload-scan.pdf");
    expect(await within(row).findByText("Stored — text not readable")).toBeInTheDocument();
    expect(within(row).getByText(/needs OCR/i)).toBeInTheDocument();
  });

  it("lists documents already on file with their page counts and fact counts", async () => {
    mockApi(
      routes({
        [`/v1/cases/${CASE_ID}/documents`]: { body: [documentDetail] },
        [`/v1/cases/${CASE_ID}/facts`]: { body: facts },
      }),
    );
    renderTab();

    expect(await screen.findByText("mri-report.pdf")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    const verified = facts.filter((fact) => fact.status === "VERIFIED").length;
    const proposed = facts.filter((fact) => fact.status === "PROPOSED").length;
    expect(
      screen.getByText(`${verified} verified · ${proposed} awaiting review`),
    ).toBeInTheDocument();
  });

  it("confirms before removing a document and surfaces a server refusal", async () => {
    const user = userEvent.setup();
    mockApi(
      routes({
        [`/v1/cases/${CASE_ID}/documents`]: { body: [documentDetail] },
        "DELETE /v1/documents/doc_1": {
          status: 409,
          body: {
            detail: { message: "2 fact(s) cite mri-report.pdf", fact_ids: ["fact_1", "fact_2"] },
          },
        },
      }),
    );
    renderTab();

    await screen.findByText("mri-report.pdf");
    await user.click(screen.getByRole("button", { name: "Remove" }));

    // Nothing is deleted on the click alone.
    expect(await screen.findByText("Remove this document?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove document" }));
    expect(await screen.findByText(/2 fact\(s\) cite mri-report.pdf/)).toBeInTheDocument();
    // Still listed: a refused removal must not half-remove the row.
    expect(screen.getAllByText("mri-report.pdf").length).toBeGreaterThan(0);
  });

  it("reports case setup against real backend state once anything is on file", async () => {
    mockApi(
      routes({
        [`/v1/cases/${CASE_ID}/templates`]: { body: [letterTemplate] },
        [`/v1/cases/${CASE_ID}/documents`]: { body: [documentDetail] },
        [`/v1/cases/${CASE_ID}/facts`]: { body: facts },
        [`/v1/cases/${CASE_ID}/demands`]: { body: [demand] },
      }),
    );
    renderTab();

    expect(await screen.findByText("Case setup")).toBeInTheDocument();
    expect(await screen.findByText("Demand template")).toBeInTheDocument();
    expect(screen.getByText("1 document on file")).toBeInTheDocument();
    const proposed = facts.filter((fact) => fact.status === "PROPOSED").length;
    expect(
      await screen.findByText(
        `${proposed} proposed fact${proposed === 1 ? " requires" : "s require"} review`,
      ),
    ).toBeInTheDocument();
  });
});
