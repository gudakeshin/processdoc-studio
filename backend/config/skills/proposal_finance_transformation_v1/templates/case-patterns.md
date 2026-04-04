# Case Patterns — Anonymized Comparable Engagement Examples

Use these case pattern examples to build credibility. Real case patterns are far more compelling than generic credentials.

---

## Case Pattern Template Structure

Each case pattern should follow this format:

1. **Company profile** (anonymized)
2. **Baseline metrics** (before transformation)
3. **Approach taken** (what we did)
4. **Results achieved** (what changed)
5. **Timeline** (how long it took)
6. **Key lesson** (what we learned)

---

## Case Pattern 1: Close Acceleration — Manufacturing

**Company:** $2B+ specialty chemicals manufacturer
- Industry: Chemical manufacturing and distribution
- Geographic scope: 5 regions (US, Europe, Asia)
- Finance structure: Regional controllers + corporate close; SAP ERP
- Prior close transformation attempts: None; current process unchanged for 5+ years

**Baseline (Before):**
- Close calendar: 12 workdays (current state assessment)
- GL reconciliation effort: 45% of close time (manual, spreadsheet-based)
- Manual journal entries: 8,000-10,000 per month
- SAP control findings: 6 findings per year (GL reconciliation, journal entry controls)
- Team: 4 FTE dedicated to close, 8+ other finance staff supporting
- Audit observation: Control environment for GL was "lagging" in prior audit

**Approach:**
1. **Phase 1 (Weeks 1-4):** Current-state assessment and design
   - Mapped 12-day close process; identified GL reconciliation as biggest bottleneck
   - Found 15% of GL accounts unmapped to subledgers (data quality issue, not just process)
   - Designed future-state: Eliminate 2 approval steps, enable parallel regional closings, GL reconciliation automation rules

2. **Phase 2 (Weeks 5-10):** Build & remediation
   - Fixed unmapped GL accounts (2-week data remediation sprint)
   - Configured SAP GL reconciliation rules (auto-post routine transactions; exceptions flagged)
   - Updated close procedures; created training materials

3. **Phase 3 (Weeks 11-14):** Pilot & stabilize
   - Ran pilot close with new process using live data
   - GL reconciliation automation achieved 35% auto-posting (higher than typical 25-30%)
   - Identified 2 manual exceptions requiring judgment calls; documented procedures

4. **Phase 4 (Weeks 15-17):** Deploy
   - Executed full close with new process across all 5 regions
   - 24/7 support team available; handled 3 escalations (data quality edge cases)
   - Transitioned to business-as-usual; documented final procedures

**Results:**
- **Close calendar:** 12 days → 6 days (50% reduction)
- **GL reconciliation effort:** 45% of close → 8% of close (40-point reduction in effort)
- **Manual journal entries:** 8,000/month → 500/month (94% reduction through automation)
- **SAP control findings:** 6 → 0 in first year (fully remediated)
- **FTE savings:** 1 FTE redirected from GL reconciliation to operational finance support
- **Timeline:** 17 weeks (4 months) from kickoff to full capability
- **Ongoing support:** Minimal; one issue escalation per quarter

**Financial impact:**
- **Cost savings:** 1 FTE = $135K annually
- **Risk reduction:** 6 findings eliminated = $100K audit cost savings
- **Working capital:** Earlier P&L enabled DPO optimization = $500K cash benefit
- **Total value:** $735K annually (conservative estimate; didn't include close speed decision value)
- **Investment:** $400K engagement
- **ROI:** 1.8x in Year 1; 5x+ over 3 years

**Key lesson learned:**
"Data quality is the real bottleneck, not technology. We spent 2 weeks on data remediation and that unlocked 35% automation. If we'd skipped data cleanup and tried to automate a messy GL, we'd have gotten 15-20% automation at best."

---

## Case Pattern 2: Close Acceleration — Technology (Cloud)

**Company:** $1.5B SaaS company
- Industry: Software-as-a-Service (cloud collaboration)
- Geographic scope: Global (US HQ + 3 regional support centers)
- Finance structure: Highly centralized; using NetSuite ERP
- Prior transformation attempts: Cloud migration in Year 2 (had legacy SAP, now on NetSuite)

**Baseline (Before):**
- Close calendar: 10 workdays
- GL reconciliation effort: 40% of close (manual but better than legacy SAP)
- Manual journal entries: 5,000/month (lower than manufacturing; more automated transactional processing)
- Control findings: 4 SOX findings (lower risk profile due to cloud-native controls)
- Team: 3 FTE dedicated; 5+ part-time
- Context: Company had just migrated to NetSuite 18 months prior; legacy SAP automation not available yet

**Approach:**
1. **Phase 1 (Weeks 1-4):** Rapid assessment
   - Found that 70% of GL reconciliation was between NetSuite GL and third-party tax software (integration gap)
   - Another 20% was period-end adjustments (accruals, deferrals); 10% was variance investigation

2. **Phase 2 (Weeks 5-10):** Build
   - Implemented NetSuite-to-tax-software API (automated GL reconciliation to third-party system)
   - Created standardized accrual/deferral journal templates (reduced manual entry time by 30%)
   - Configured NetSuite close process workflow (automated email reminders, approval tracking)

3. **Phase 3 (Weeks 8-12):** Pilot (shorter pilot cycle due to simpler environment)
   - Ran 2 pilot months; fine-tuned API integration (one data mapping issue found and fixed)

4. **Phase 4 (Weeks 13-14):** Deploy
   - Full implementation; very clean go-live
   - Minimal issues

**Results:**
- **Close calendar:** 10 days → 5 days (50% reduction)
- **GL reconciliation effort:** 40% → 10% of close (automation of integration + accruals)
- **Manual journal entries:** 5,000/month → 1,000/month
- **Control findings:** 4 → 0 in Year 1 (control automation for high-risk accounts)
- **FTE impact:** No headcount reduction; team redeployed to monthly close analytics and close process continuous improvement
- **Timeline:** 14 weeks (3 months) — faster than manufacturing due to simpler environment and recent cloud migration
- **Cost:** Lower than manufacturing ($250K due to fewer team members and shorter timeline)

**Financial impact:**
- **Cost savings:** 0.5 FTE redeployed = $67.5K value (not headcount elimination; redeployment)
- **Risk reduction:** 4 findings eliminated = $80K audit cost savings
- **Decision speed:** 5-day close enables faster monthly board reporting = $200K+ estimated value
- **Total value:** $347.5K+ annually
- **Investment:** $250K engagement
- **ROI:** 1.4x in Year 1; 2-3x over 3 years

**Key lesson learned:**
"Cloud systems (NetSuite, Workday) enable faster close because automation is built-in and controls are stronger. Legacy SAP requires more custom work and data remediation. If you're already cloud-native, close acceleration is achievable in 3 months vs. 4 months for legacy systems."

---

## Case Pattern 3: GBS Transformation — Financial Services

**Company:** $5B+ financial services firm
- Industry: Regional commercial bank
- Geographic scope: 8 states + HQ
- Finance structure: Each regional office had local finance team; significant duplication
- Prior transformation attempts: None; finance organization was decentralized for 20+ years

**Baseline (Before):**
- Finance cost: 0.9% of revenue = $45M annually
- Headcount: 450 finance FTE (0.009 per dollar of assets, vs. industry benchmark 0.004-0.005)
- Process variance: 8 different close procedures across regions
- GBS penetration: 20% (only HR shared services; finance was local)
- Technology: Mixed SAP/legacy systems; data warehouse consolidation limited
- Control maturity: Manual controls dominant; frequent audit findings

**Approach:**
1. **Phase 1 (Weeks 1-6):** Assess organization and design target state
   - Benchmarked finance cost; identified $10-15M annual reduction opportunity
   - Designed 3-region GBS hub model (consolidate transactional finance, keep analytical in regions)
   - Planned 18-month transition (phased vs. big bang)

2. **Phase 2 (Months 2-6):** Hire & train GBS team
   - Recruited 60 FTE GBS team in 2 locations (US onshore + low-cost center nearshore)
   - Detailed process mapping and standardization (eliminate 8 variations; create 1 standard close)
   - System infrastructure (dedicated GL, AR/AP systems in GBS; data feeds from regional systems)

3. **Phase 3 (Months 7-14):** Phased transition by process
   - Month 7-8: GL reconciliation moves to GBS (requires GL data standardization)
   - Month 9-10: AR/AP processing moves to GBS
   - Month 11-12: Period-end close and consolidation
   - Month 13-14: Final transition; legacy finance teams downsize

4. **Phase 4 (Months 15-18):** Stabilize & optimize
   - GBS productivity ramp-up (50% productivity Month 1, 75% Month 2, 90% Month 3, 100% Month 4-5)
   - Automation opportunities identified in GBS (RPA for AP exceptions, GL automated scheduling)

**Results:**
- **Finance cost:** 0.9% → 0.6% of revenue (33% reduction = $15M annually)
  - Breakdown: 15M in labor cost reduction, -$2M in GBS startup, -$1M in system costs = net $12M year 1
- **Headcount:** 450 → 325 FTE (but improved quality through standardization)
- **Process standardization:** 8 close procedures → 1 standardized procedure (enabling consistency, training, auditing)
- **GBS penetration:** 20% → 70% (planned; achieved 60% by Month 18)
- **Control maturity:** Audit findings dropped from 12 to 3 (automation and standardization reduced manual control variance)
- **Time-to-productivity:** GBS ramp-up took 6 months (longer than 3-month assumption due to organizational complexity)
- **Timeline:** 18 months from kickoff to full operational target state (phased approach)

**Financial impact:**
- **Year 1 cost savings:** $12M net (gross $15M less GBS ramp-up and system costs)
- **Ongoing annual savings:** $15M (once fully ramped)
- **Quality improvements:** Reduced audit findings = $200K+ annual savings
- **Scalability value:** 3-year projection shows $25M+ cumulative benefit
- **Investment:** $3M (GBS setup, training, systems, change management)
- **ROI:** 4x in Year 1; 5-10x over 3 years

**Key lesson learned:**
"GBS transformation takes longer than expected (18 months vs. 12 months) due to productivity ramp-up and organizational change management. Our assumptions underestimated the time staff in regional offices spent on ad-hoc tasks (outside close). Phased transition is critical; don't do big bang. The 'hidden work' only surfaces when you try to consolidate."

---

## Case Pattern 4: FP&A Transformation — Mid-Cap Manufacturer

**Company:** $800M mid-cap industrial manufacturer
- Industry: Equipment manufacturing and industrial components
- Geographic scope: 3 plants, 2 sales regions, HQ finance
- Finance structure: CFO, Controller, one FP&A manager
- Prior transformation attempts: One failed system implementation (3 years prior)

**Baseline (Before):**
- Planning cycle time: 8 weeks (too long; decisions made mid-cycle)
- Forecast accuracy: ±9% (high variance; CFO making decisions on stale data)
- Scenario capability: Only 2 base scenarios possible (time constraint)
- Planning tools: Excel and Access database (not integrated with GL)
- Team: 1 FTE FP&A analyst + part-time CFO support (understaffed)
- Context: Recent failed system implementation made team skeptical of planning tools

**Approach:**
1. **Phase 1 (Weeks 1-4):** Assess planning maturity and design
   - Found that 40% of FP&A time was spent on manual data consolidation (5 plants pulling from different systems)
   - Designed planning process (3-week cycle vs. 8 weeks; rolling 13-week forecast + annual budget)
   - Selected tool (decided NOT to do full system migration; started with enhanced Excel + cloud data consolidation)

2. **Phase 2 (Weeks 5-12):** Build & train
   - Implemented data consolidation layer (cloud-based ETL pulling from 3 plant systems)
   - Created Excel planning templates (revenue drivers, COGS variance, SG&A)
   - Trained plant controllers and FP&A team on new process

3. **Phase 3 (Weeks 13-16):** Pilot (2 planning cycles)
   - Q1 forecast: New process took 2.5 weeks (vs. 8 weeks baseline); models worked
   - Q2 forecast: Refined models; process now 2 weeks (including iterations)

4. **Phase 4 (Weeks 17+):** Ongoing operation
   - Quarterly forecasts using new 3-week cycle
   - Added scenario modeling (CFO can now run 10+ scenarios in 4 hours, vs. not possible before)
   - Improved forecast accuracy over 2 quarters

**Results:**
- **Planning cycle time:** 8 weeks → 3 weeks (62% reduction)
- **Forecast accuracy:** ±9% → ±4% (after 2 quarters; continued improvement trajectory)
- **Scenario capability:** 2 scenarios → 20+ scenarios (enabled CFO to model sensitivity)
- **FTE productivity:** 40% of analyst time freed from data consolidation (able to focus on analytics)
- **Timeline:** 4 months to capability; ongoing improvement
- **System cost:** $50K (data consolidation tools + Excel framework) vs. $800K+ full system would have cost

**Financial impact:**
- **Planning efficiency:** 40% FTE time savings = $40K (but analyst kept; redeployed to analytics)
- **Decision quality:** Better forecast accuracy + scenario capability = estimated $1-2M value (improved supply chain decisions, working capital)
- **System cost avoided:** Would have cost $800K for full planning system; this solution cost $50K
- **Total value:** $1.05-2.05M (depending on decision quality impact assumptions)
- **Investment:** $200K engagement + $50K system
- **ROI:** 3-5x in Year 1

**Key lesson learned:**
"You don't need a new system to improve planning. This CFO had a tool problem (Excel), not a system problem. A data consolidation layer + process discipline gave 80% of the benefit at 10% of the cost. Full ERP planning modules are overkill for many mid-market companies."

---

## How to use case patterns in proposals

### Option 1: Single case pattern (brief mention)
"We've led similar close accelerations for 5+ mid-market manufacturers. For a comparable $2B specialty chemicals company, we reduced close from 12 to 6 days in 4 months, delivering $1M+ value."

### Option 2: Multiple case patterns (full section)
Dedicate 3-5 pages to 2-3 detailed case patterns showing:
- Company profile (anonymized but comparable)
- Baseline metrics (before)
- Results achieved (after)
- Timeline (how long)
- Key learning (what surprised us)

### Option 3: Case pattern comparison table
Create a table showing 3-4 case patterns side-by-side, comparing baseline metrics, results, and timelines.

---

## What makes a strong case pattern

✅ **Strong case patterns:**
- Comparable to your client (similar size, industry, complexity)
- Specific metrics (not "significantly improved")
- Realistic results (not over-optimized)
- Shows key learning (what actually happened, not what we planned)
- Anonymized (no client names; describe in generic terms)

❌ **Weak case patterns:**
- Too small or too large (not credible for your client's scale)
- Vague results ("improved efficiency")
- Over-optimized (cherry-picked best case)
- No learning (just a success story)
- Too detailed (more than 1 page per case pattern)

---

## Anonymization guidelines

**DO:**
- Company size: "$2B+ specialty chemicals manufacturer"
- Industry: "Mid-cap equipment manufacturer"
- Geography: "5-region European chemical company"
- Metrics: Actual before/after numbers
- Timeline: Actual months/weeks

**DON'T:**
- Name the actual company
- Identify the CFO or key executives
- Mention specific unique products or business models that would identify them
- Share proprietary processes or systems details

Anonymization protects client confidentiality while still proving you've done the work before.

