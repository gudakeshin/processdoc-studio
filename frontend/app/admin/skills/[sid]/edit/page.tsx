export default async function EditSkillPage({ params }: { params: Promise<{ sid: string }> }) {
  const { sid } = await params;
  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-semibold">Edit Skill</h1>
      <p className="text-sm text-[var(--text-muted)]">Skill id: {sid}</p>
    </div>
  );
}
