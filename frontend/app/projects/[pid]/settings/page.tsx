import Link from "next/link";

export default async function SettingsPage({ params }: { params: Promise<{ pid: string }> }) {
  const { pid } = await params;
  const tabs = [
    { href: `/projects/${pid}/settings/formats`, label: "Output Types" },
    { href: `/projects/${pid}/settings/brand`, label: "Brand" },
    { href: `/projects/${pid}/settings/dpdp`, label: "DPDP" },
    { href: `/projects/${pid}/settings/quality`, label: "Quality" },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Project Settings</h1>
      <div className="flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className="rounded-md border border-[color:color-mix(in_srgb,var(--primary-700)_30%,transparent)] bg-white px-3 py-1.5 text-sm text-[var(--primary-900)] hover:bg-[var(--primary-50)]"
          >
            {tab.label}
          </Link>
        ))}
      </div>
    </div>
  );
}
