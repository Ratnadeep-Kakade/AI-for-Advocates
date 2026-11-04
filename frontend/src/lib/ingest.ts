import { useStore } from "../store";
import { fetchDocuments, uploadDocument } from "./api";
import { uid } from "./util";

const POLL_INTERVAL_MS = 6000;
const MAX_POLLS = 600; // ~1h: 500-600 page PDFs ingest slowly on CPU.

// Adds files to a case, uploads each one directly to GCS via signed URL,
// then polls the processing status until ingestion completes or fails.
export async function ingestFiles(caseId: string, files: File[]) {
  const st = useStore.getState();
  await Promise.all(
    files.map(async (f) => {
      const id = uid();
      st.addDoc({ id, caseId, name: f.name, size: f.size, status: "processing", addedAt: Date.now() });
      try {
        const res = await uploadDocument(caseId, f);
        useStore.getState().patchDoc(id, { id: res.id });
        if (res.processingStatus === "completed") {
          useStore.getState().patchDoc(res.id, { status: "analyzed" });
          return;
        }
        if (res.processingStatus === "failed") {
          useStore.getState().patchDoc(res.id, { status: "failed" });
          return;
        }
        for (let attempt = 0; attempt < MAX_POLLS; attempt++) {
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
          const docs = await fetchDocuments(caseId);
          const doc = docs.find((d) => d.document_id === res.id);
          if (!doc) continue;
          if (doc.processing_status === "completed") {
            useStore.getState().patchDoc(res.id, { status: "analyzed" });
            return;
          }
          if (doc.processing_status === "failed") {
            useStore.getState().patchDoc(res.id, { status: "failed" });
            return;
          }
        }
        // Still processing after the polling budget: leave the document in
        // "processing" (large files can legitimately take over an hour).
      } catch {
        useStore.getState().patchDoc(id, { status: "failed" });
      }
    })
  );
}
