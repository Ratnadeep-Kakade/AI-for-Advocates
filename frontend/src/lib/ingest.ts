import { useStore } from "../store";
import { uploadDocument } from "./api";
import { uid } from "./util";

// Adds files to a case, uploads each one, and tracks status in the store.
export async function ingestFiles(caseId: string, files: File[]) {
  const st = useStore.getState();
  await Promise.all(
    files.map(async (f) => {
      const id = uid();
      st.addDoc({ id, caseId, name: f.name, size: f.size, status: "processing", addedAt: Date.now() });
      try {
        const res = await uploadDocument(caseId, f);
        useStore.getState().patchDoc(id, { id: res.id, status: "analyzed" });
      } catch {
        useStore.getState().patchDoc(id, { status: "failed" });
      }
    })
  );
}
