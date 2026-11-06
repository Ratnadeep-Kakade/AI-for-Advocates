import { useStore } from "../store";
import type { CaseDoc } from "../types";
import { fetchDocuments, uploadDocument } from "./api";
import { uid } from "./util";

const POLL_INTERVAL_MS = 5000;
const MAX_POLLS = 720; // ~1h

/**
 * Synchronize all documents for a case between backend and local store.
 * Authoritative: remote state is the source of truth for registered docs.
 * Prevents race conditions, duplicate entries, and status flickering.
 */
export async function syncCaseDocuments(caseId: string): Promise<void> {
  const remoteDocs = await fetchDocuments(caseId);
  const store = useStore.getState();

  const existingForCase = store.docs.filter((d) => d.caseId === caseId);
  const existingMap = new Map(existingForCase.map((d) => [d.id, d]));

  const syncedCaseDocs: CaseDoc[] = remoteDocs.map((rDoc) => {
    let stage = "Processed";
    let newStatus: "processing" | "analyzed" | "failed" = "analyzed";

    if (rDoc.processing_status === "completed") {
      newStatus = "analyzed";
      stage = "Processed";
    } else if (rDoc.processing_status === "failed") {
      newStatus = "failed";
      stage = "Failed";
    } else {
      newStatus = "processing";
      const raw = (rDoc.processing_stage || "").toLowerCase();
      if (raw.includes("embed")) stage = "Embedding";
      else if (raw.includes("chunk") || raw.includes("pars")) stage = "Chunking";
      else if (raw.includes("upload") || raw.includes("download")) stage = "Uploading";
      else stage = "Chunking";
    }

    const existing = existingMap.get(rDoc.document_id);
    return {
      id: rDoc.document_id,
      caseId,
      name: rDoc.title || rDoc.original_filename,
      size: rDoc.file_size,
      status: newStatus,
      stage: existing?.stage && existing.status === "processing" ? existing.stage : stage,
      addedAt: existing ? existing.addedAt : Date.now(),
    };
  });

  // Preserve local temporary docs that were created very recently (within 60s)
  // and are still actively uploading to GCS.
  const serverIds = new Set(remoteDocs.map((r) => r.document_id));
  const now = Date.now();
  const recentInFlight = existingForCase.filter(
    (d) => !serverIds.has(d.id) && d.status === "processing" && now - d.addedAt < 60000
  );

  store.setCaseDocs(caseId, [...syncedCaseDocs, ...recentInFlight]);
}

// Adds files to a case, uploads each one directly to GCS via signed URL,
// then polls the processing status through pipeline stages: Uploading -> Chunking -> Embedding -> Processed.
export async function ingestFiles(caseId: string, files: File[]) {
  const st = useStore.getState();
  await Promise.all(
    files.map(async (f) => {
      const id = uid();
      st.addDoc({
        id,
        caseId,
        name: f.name,
        size: f.size,
        status: "processing",
        stage: "Uploading",
        addedAt: Date.now(),
      });
      let activeDocId = id;
      try {
        const res = await uploadDocument(caseId, f, (stageName) => {
          useStore.getState().patchDoc(id, { stage: stageName });
        });
        activeDocId = res.id;
        useStore.getState().patchDoc(id, { id: res.id, stage: "Chunking" });
        if (res.processingStatus === "completed") {
          useStore.getState().patchDoc(res.id, { status: "analyzed", stage: "Processed" });
          return;
        }
        if (res.processingStatus === "failed") {
          useStore.getState().patchDoc(res.id, { status: "failed", stage: "Failed" });
          return;
        }

        const startTime = Date.now();
        for (let attempt = 0; attempt < MAX_POLLS; attempt++) {
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
          try {
            const docs = await fetchDocuments(caseId);
            const doc = docs.find((d) => d.document_id === res.id);
            if (!doc) continue;
            if (doc.processing_status === "completed") {
              useStore.getState().patchDoc(res.id, { status: "analyzed", stage: "Processed" });
              return;
            }
            if (doc.processing_status === "failed") {
              useStore.getState().patchDoc(res.id, { status: "failed", stage: "Failed" });
              return;
            }

            // Map server stage or time-based progression
            let currentStage = "Chunking";
            if (doc.processing_stage) {
              const raw = doc.processing_stage.toLowerCase();
              if (raw.includes("embed")) currentStage = "Embedding";
              else if (raw.includes("chunk") || raw.includes("pars")) currentStage = "Chunking";
              else if (raw.includes("upload") || raw.includes("download")) currentStage = "Uploading";
              else if (raw.includes("complet")) currentStage = "Processed";
            } else {
              const elapsed = Date.now() - startTime;
              // Normal pipeline: 0-6s Chunking, 6s+ Embedding
              currentStage = elapsed > 6000 ? "Embedding" : "Chunking";
            }
            useStore.getState().patchDoc(res.id, { stage: currentStage });
          } catch {
            // Transient network failure: keep polling
          }
        }
      } catch {
        useStore.getState().patchDoc(activeDocId, { status: "failed", stage: "Failed" });
      }
    })
  );
}
