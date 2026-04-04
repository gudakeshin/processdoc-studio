import { DocumentUploader } from "@/components/documents/DocumentUploader";

export default async function WorkspacePage({ params }: { params: Promise<{ pid: string }> }) {
  const { pid } = await params;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Document Workspace</h1>
      <p className="text-sm text-[var(--text-muted)]">Project: {pid}</p>
      <DocumentUploader projectId={pid} />
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4 text-sm">
          <h3 className="font-medium">Workspace folders</h3>
          <ul className="mt-2 list-disc pl-5 text-xs text-[var(--text-muted)]">
            <li>`CONTEXT.md`</li>
            <li>`source_docs/`</li>
            <li>`parsed_docs/`</li>
            <li>`runs/`</li>
          </ul>
        </div>
        <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4 text-sm">
          <h3 className="font-medium">How documents are used</h3>
          <p className="mt-2 text-xs text-[var(--text-muted)]">
            Uploaded files are chunked into `parsed_docs` and retrieved into assembled context during run planning and generation.
          </p>
        </div>
      </div>
    </div>
  );
}
