"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

type WizardStep = "template" | "assumptions" | "review" | "complete";

type TemplateType = "startup" | "enterprise" | "manufacturing" | "retail" | "services";

type AssumptionData = {
  revenue: number;
  revenueGrowth: number;
  grossMargin: number;
  operatingMargin: number;
  taxRate: number;
  capexPercent: number;
  workingCapitalPercent: number;
  discountRate: number;
};

type ModelData = {
  name: string;
  template: TemplateType;
  assumptions: AssumptionData;
};

const TEMPLATES: Record<TemplateType, { label: string; description: string }> = {
  startup: {
    label: "Startup",
    description: "High growth, early stage company with rapid scaling",
  },
  enterprise: {
    label: "Enterprise",
    description: "Established company with mature operations",
  },
  manufacturing: {
    label: "Manufacturing",
    description: "Production-focused business with inventory",
  },
  retail: {
    label: "Retail",
    description: "Retail operations with seasonal patterns",
  },
  services: {
    label: "Services",
    description: "Service-based business with labor costs",
  },
};

const TEMPLATE_DEFAULTS: Record<TemplateType, AssumptionData> = {
  startup: {
    revenue: 1000000,
    revenueGrowth: 0.5,
    grossMargin: 0.7,
    operatingMargin: -0.1,
    taxRate: 0.21,
    capexPercent: 0.05,
    workingCapitalPercent: 0.1,
    discountRate: 0.12,
  },
  enterprise: {
    revenue: 100000000,
    revenueGrowth: 0.1,
    grossMargin: 0.4,
    operatingMargin: 0.15,
    taxRate: 0.21,
    capexPercent: 0.03,
    workingCapitalPercent: 0.08,
    discountRate: 0.08,
  },
  manufacturing: {
    revenue: 50000000,
    revenueGrowth: 0.08,
    grossMargin: 0.35,
    operatingMargin: 0.12,
    taxRate: 0.21,
    capexPercent: 0.08,
    workingCapitalPercent: 0.15,
    discountRate: 0.09,
  },
  retail: {
    revenue: 25000000,
    revenueGrowth: 0.05,
    grossMargin: 0.4,
    operatingMargin: 0.05,
    taxRate: 0.21,
    capexPercent: 0.04,
    workingCapitalPercent: 0.2,
    discountRate: 0.1,
  },
  services: {
    revenue: 10000000,
    revenueGrowth: 0.15,
    grossMargin: 0.65,
    operatingMargin: 0.2,
    taxRate: 0.21,
    capexPercent: 0.02,
    workingCapitalPercent: 0.05,
    discountRate: 0.11,
  },
};

export function FinancialModelWizard({
  onComplete,
}: {
  onComplete: (data: ModelData) => void;
}) {
  const [step, setStep] = useState<WizardStep>("template");
  const [modelData, setModelData] = useState<ModelData>({
    name: "",
    template: "enterprise",
    assumptions: TEMPLATE_DEFAULTS.enterprise,
  });

  const handleTemplateSelect = (template: TemplateType) => {
    setModelData({
      ...modelData,
      template,
      assumptions: TEMPLATE_DEFAULTS[template],
    });
    setStep("assumptions");
  };

  const handleAssumptionChange = (key: keyof AssumptionData, value: number) => {
    setModelData({
      ...modelData,
      assumptions: {
        ...modelData.assumptions,
        [key]: value,
      },
    });
  };

  const handleNameChange = (name: string) => {
    setModelData({ ...modelData, name });
  };

  const handleComplete = () => {
    if (modelData.name.trim()) {
      onComplete(modelData);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      {/* Progress Indicator */}
      <div className="mb-8 flex items-center justify-between">
        {(["template", "assumptions", "review", "complete"] as const).map(
          (s, idx) => (
            <div key={s} className="flex items-center">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold ${
                  step === s
                    ? "bg-[#86BC24] text-white"
                    : (["template", "assumptions", "review", "complete"] as const).indexOf(
                        s
                      ) < (["template", "assumptions", "review", "complete"] as const).indexOf(step)
                    ? "bg-[#86BC24] text-white"
                    : "bg-[#f0f0f0] text-[#4C4C4C]"
                }`}
              >
                {idx + 1}
              </div>
              {idx < 3 && <div className="mx-2 h-0.5 w-12 bg-[#f0f0f0]" />}
            </div>
          )
        )}
      </div>

      {/* Step 1: Select Template */}
      {step === "template" && (
        <div className="space-y-4">
          <div>
            <h2 className="text-xl font-semibold text-[#0F0B0B]">
              Select a Template
            </h2>
            <p className="mt-1 text-sm text-[#4C4C4C]">
              Choose a template that best matches your business model
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {(Object.entries(TEMPLATES) as [TemplateType, typeof TEMPLATES.startup][]).map(
              ([templateId, template]) => (
                <Card
                  key={templateId}
                  onClick={() => handleTemplateSelect(templateId)}
                  className={`cursor-pointer transition ${
                    modelData.template === templateId
                      ? "border-[#86BC24] bg-[#f0f8f0]"
                      : "hover:border-[#86BC24]"
                  }`}
                >
                  <div className="p-4">
                    <h3 className="font-semibold text-[#0F0B0B]">
                      {template.label}
                    </h3>
                    <p className="mt-1 text-xs text-[#4C4C4C]">
                      {template.description}
                    </p>
                  </div>
                </Card>
              )
            )}
          </div>
        </div>
      )}

      {/* Step 2: Enter Assumptions */}
      {step === "assumptions" && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-semibold text-[#0F0B0B]">
              Model Name & Assumptions
            </h2>
            <p className="mt-1 text-sm text-[#4C4C4C]">
              Customize the financial assumptions for your model
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[#0F0B0B]">
              Model Name
            </label>
            <Input
              type="text"
              placeholder="e.g., FY2024 Operating Plan"
              value={modelData.name}
              onChange={(e) => handleNameChange(e.target.value)}
              className="mt-1"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-[#4C4C4C]">
                Annual Revenue
              </label>
              <Input
                type="number"
                value={modelData.assumptions.revenue}
                onChange={(e) =>
                  handleAssumptionChange("revenue", parseFloat(e.target.value))
                }
                className="mt-1"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#4C4C4C]">
                Revenue Growth Rate (%)
              </label>
              <Input
                type="number"
                step="0.01"
                value={(modelData.assumptions.revenueGrowth * 100).toFixed(1)}
                onChange={(e) =>
                  handleAssumptionChange(
                    "revenueGrowth",
                    parseFloat(e.target.value) / 100
                  )
                }
                className="mt-1"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#4C4C4C]">
                Gross Margin (%)
              </label>
              <Input
                type="number"
                step="0.01"
                value={(modelData.assumptions.grossMargin * 100).toFixed(1)}
                onChange={(e) =>
                  handleAssumptionChange(
                    "grossMargin",
                    parseFloat(e.target.value) / 100
                  )
                }
                className="mt-1"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#4C4C4C]">
                Operating Margin (%)
              </label>
              <Input
                type="number"
                step="0.01"
                value={(modelData.assumptions.operatingMargin * 100).toFixed(1)}
                onChange={(e) =>
                  handleAssumptionChange(
                    "operatingMargin",
                    parseFloat(e.target.value) / 100
                  )
                }
                className="mt-1"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#4C4C4C]">
                Tax Rate (%)
              </label>
              <Input
                type="number"
                step="0.01"
                value={(modelData.assumptions.taxRate * 100).toFixed(1)}
                onChange={(e) =>
                  handleAssumptionChange(
                    "taxRate",
                    parseFloat(e.target.value) / 100
                  )
                }
                className="mt-1"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-[#4C4C4C]">
                Discount Rate (%)
              </label>
              <Input
                type="number"
                step="0.01"
                value={(modelData.assumptions.discountRate * 100).toFixed(1)}
                onChange={(e) =>
                  handleAssumptionChange(
                    "discountRate",
                    parseFloat(e.target.value) / 100
                  )
                }
                className="mt-1"
              />
            </div>
          </div>

          <div className="flex gap-3">
            <Button
              variant="secondary"
              onClick={() => setStep("template")}
              className="flex-1"
            >
              Back
            </Button>
            <Button
              onClick={() => setStep("review")}
              className="flex-1"
            >
              Review
            </Button>
          </div>
        </div>
      )}

      {/* Step 3: Review */}
      {step === "review" && (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-semibold text-[#0F0B0B]">
              Review Your Model
            </h2>
            <p className="mt-1 text-sm text-[#4C4C4C]">
              Verify all assumptions before creating the model
            </p>
          </div>

          <Card className="bg-[#f9f9f9]">
            <div className="p-4 space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <p className="text-xs text-[#4C4C4C]">Model Name</p>
                  <p className="mt-1 font-semibold text-[#0F0B0B]">
                    {modelData.name}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[#4C4C4C]">Template</p>
                  <p className="mt-1 font-semibold text-[#0F0B0B]">
                    {TEMPLATES[modelData.template].label}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[#4C4C4C]">Annual Revenue</p>
                  <p className="mt-1 font-semibold text-[#0F0B0B]">
                    ${(modelData.assumptions.revenue / 1000000).toFixed(1)}M
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[#4C4C4C]">Revenue Growth</p>
                  <p className="mt-1 font-semibold text-[#0F0B0B]">
                    {(modelData.assumptions.revenueGrowth * 100).toFixed(1)}%
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[#4C4C4C]">Gross Margin</p>
                  <p className="mt-1 font-semibold text-[#0F0B0B]">
                    {(modelData.assumptions.grossMargin * 100).toFixed(1)}%
                  </p>
                </div>
                <div>
                  <p className="text-xs text-[#4C4C4C]">Operating Margin</p>
                  <p className="mt-1 font-semibold text-[#0F0B0B]">
                    {(modelData.assumptions.operatingMargin * 100).toFixed(1)}%
                  </p>
                </div>
              </div>
            </div>
          </Card>

          <div className="flex gap-3">
            <Button
              variant="secondary"
              onClick={() => setStep("assumptions")}
              className="flex-1"
            >
              Back
            </Button>
            <Button
              onClick={handleComplete}
              className="flex-1"
            >
              Create Model
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
