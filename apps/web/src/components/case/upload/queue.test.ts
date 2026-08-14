import { describe, expect, it } from "vitest";

import { uploadLimits } from "@/test/fixtures";
import { createEventStreamParser } from "@/lib/api/client";
import { extensionOf, limitsForDocuments, limitsForTemplate, validateFile } from "./queue";

function fileOf(name: string, bytes: number): File {
  const file = new File(["x"], name, { type: "application/octet-stream" });
  Object.defineProperty(file, "size", { value: bytes });
  return file;
}

describe("upload validation", () => {
  const documentLimits = limitsForDocuments(uploadLimits);
  const templateLimits = limitsForTemplate(uploadLimits);

  it("accepts a file whose extension and size the server allows", () => {
    expect(validateFile(fileOf("records.pdf", 1024), documentLimits)).toBeNull();
  });

  it("rejects an extension the server does not accept, and says which are allowed", () => {
    const problem = validateFile(fileOf("payload.exe", 1024), documentLimits);
    expect(problem).toContain(".exe");
    expect(problem).toContain(".pdf");
  });

  it("rejects a file over the server's size limit in megabytes, not bytes", () => {
    const problem = validateFile(fileOf("huge.pdf", 60 * 1024 * 1024), documentLimits);
    expect(problem).toContain("60.0 MB");
    expect(problem).toContain("50.0 MB");
  });

  it("rejects an empty file", () => {
    expect(validateFile(fileOf("empty.pdf", 0), documentLimits)).toBe("File is empty.");
  });

  it("allows only .docx for the template, even though evidence accepts more", () => {
    expect(validateFile(fileOf("template.docx", 2048), templateLimits)).toBeNull();
    expect(validateFile(fileOf("records.pdf", 2048), templateLimits)).toContain(".pdf");
  });

  it("applies the template's own size limit rather than the document one", () => {
    // 30MB: under the 50MB document limit, over the 20MB template limit.
    expect(validateFile(fileOf("big.docx", 30 * 1024 * 1024), templateLimits)).toContain("20.0 MB");
    expect(validateFile(fileOf("big.pdf", 30 * 1024 * 1024), documentLimits)).toBeNull();
  });

  it("validates nothing until the server has told it what the limits are", () => {
    expect(validateFile(fileOf("anything.xyz", 1), null)).toBeNull();
    expect(limitsForDocuments(undefined)).toBeNull();
  });

  it("reads the extension case-insensitively", () => {
    expect(extensionOf("SCAN.PDF")).toBe(".pdf");
    expect(extensionOf("no-extension")).toBe("");
    expect(validateFile(fileOf("SCAN.PDF", 100), documentLimits)).toBeNull();
  });
});

describe("job event stream parsing", () => {
  it("returns one event per complete frame", () => {
    const parser = createEventStreamParser();
    const events = parser.push(
      'event: stage\ndata: {"stage":"extracting","status":"running"}\n\n' +
        'event: done\ndata: {"job_id":"job_1","status":"COMPLETED"}\n\n',
    );

    expect(events.map((event) => event.event)).toEqual(["stage", "done"]);
    expect(JSON.parse(events[0].data).stage).toBe("extracting");
  });

  it("holds a frame split across chunks until it is complete", () => {
    const parser = createEventStreamParser();

    expect(parser.push("event: stage\ndata: {\"stage\":\"extr")).toEqual([]);
    const events = parser.push('acting","status":"completed"}\n\n');

    expect(events).toHaveLength(1);
    expect(JSON.parse(events[0].data).status).toBe("completed");
  });

  it("ignores keep-alive comment frames", () => {
    const parser = createEventStreamParser();
    expect(parser.push(": keep-alive\n\n")).toEqual([]);
  });
});
