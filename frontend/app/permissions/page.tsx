export default function PermissionsPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Permissions & Access Scope</h1>
      <p className="text-sm text-[var(--text-muted)]">
        Approve app-level actions, manage folder scope, and inspect connector grants before task execution.
      </p>
      <div className="rounded-lg border border-[var(--surface-border-strong)] bg-[var(--surface-default)] p-4 text-sm">
        <ul className="space-y-2">
          <li>Allowed folders: `/workspace/project-alpha`, `/workspace/shared-templates`</li>
          <li>Connector policy: CRM (read), Drive (read/write), Email (blocked)</li>
          <li>Computer-use policy: Prompt for every app switch</li>
        </ul>
      </div>
    </div>
  );
}
