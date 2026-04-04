# Phased Approach Template

Standard four-phase structure for finance transformation engagements. Customize duration and scope based on client context.

---

## Standard 4-Phase Approach (Close Acceleration Example)

### Phase 1: Diagnose & Design (Weeks 1-4)

**Objective:** Understand current state, identify root causes, design future-state process

**Key activities:**
- **Current-state assessment**
  - Document close process from first transaction to final P&L
  - Interview key stakeholders (close owner, GL manager, regional controllers, audit)
  - Identify current close calendar, critical path tasks, pain points
  - Map subledger-to-GL reconciliation process (identify manual steps, data quality issues)
  - Assess technology usage (SAP, consolidation tool, reconciliation tools)

- **Root cause analysis**
  - Categorize bottlenecks by type: Process, Organization, Technology, Data
  - For GL reconciliation: Are the manual steps due to data quality, process design, or insufficient automation?
  - For approval workflow: Are all 8 sign-offs necessary or are some redundant?

- **Benchmark assessment**
  - Compare current state to industry best practices
  - Identify quick wins (no-cost or low-cost improvements)
  - Calculate opportunity size (time, cost, risk reduction)

- **Design future-state process**
  - Streamline workflow (eliminate redundant approvals, enable parallel execution)
  - Design GL reconciliation automation (identify account categories, mapping rules, exception handling)
  - Define new roles and responsibilities

- **Develop workplan & governance**
  - Create detailed project plan (phases, milestones, decision gates)
  - Establish steering committee (CFO, close owner, IT, external audit)
  - Define escalation procedures and change control

**Deliverables:**
- Current-state process documentation (swim lanes or process maps)
- Root cause summary (table: bottleneck, category, impact, root cause)
- Close calendar analysis (task breakdown showing where time is spent)
- Opportunity assessment (quantified impact: days, cost, risk reduction)
- Design document: Future-state close process
- Project plan with phases and decision gates

**Client commitments:**
- **Availability**: Close owner 50% time (minimum 2 days/week), GL manager 25% time, 2-3 regional controllers (sample)
- **Data access**: Read access to SAP, consolidation tool, bank feeds, subledger systems
- **Decisions**: 2-3 steering committee meetings (1 kick-off, progress reviews, design approval)
- **Timeline**: 4 weeks assumes 1 decision cycle; more if multiple business unit close models

**Decision gate (End of Week 4):**
- ✓ Do we agree on root causes? Do we agree this is the right scope?
- ✓ Is 6-day close calendar realistic, or should we adjust target?
- ✓ Should we proceed with full transformation or focus on quick wins first?

---

### Phase 2: Build & Configure (Weeks 5-10, overlaps Phase 1 Week 4)

**Objective:** Implement process changes, configure technology, prepare for pilot

**Key activities:**
- **Process redesign**
  - Update close procedures with new workflow
  - Design GL reconciliation rules (which accounts can auto-reconcile, which need manual judgment)
  - Eliminate redundant approvals
  - Create new role descriptions (close coordinator, GL reconciliation specialist)

- **Data quality remediation**
  - Assess GL account hierarchy (are all accounts properly classified?)
  - Identify and remediate unmapped subledger accounts
  - Create GL master data governance going forward
  - Run reconciliation validation scripts to identify chronic problem areas

- **System configuration** (if SAP or consolidation tool is in scope)
  - Configure GL reconciliation automation (auto-post routine transactions)
  - Set up real-time GL-to-subledger feeds
  - Create new reports for close tracking

- **Build tools**
  - Create Excel/Power Query templates if automation not tech-enabled
  - Design exception handling procedures (what happens when auto-reconciliation fails?)
  - Create close calendar dashboard (tracking progress against milestones)

- **Change management**
  - Design training curriculum (new process, new tools, new roles)
  - Communicate timeline and impact to affected staff
  - Identify quick wins to build momentum

**Deliverables:**
- Updated close procedures (documented in SharePoint or Confluence)
- GL reconciliation rules matrix (accounts, auto-post logic, exceptions)
- Data remediation report (unmapped accounts fixed, quality metrics)
- System configuration specifications (if applicable)
- Training materials (process overview, role-specific training, job aids)
- Close calendar tracker (template)

**Client commitments:**
- **Availability**: Close owner 75% time, GL manager 50% time, IT resources for config (if system changes)
- **Sign-offs**: Process design, GL rules, data quality standards
- **Readiness**: Prepare pilot data (one full close cycle)
- **Timeline**: 6 weeks (Weeks 5-10), accounting for data remediation time

**Decision gate (End of Week 8 or 10):**
- ✓ Is data quality sufficient to proceed with automation?
- ✓ Are new procedures documented and understood?
- ✓ Are we ready for pilot, or do we need extended data remediation?

---

### Phase 3: Pilot & Stabilize (Weeks 11-14)

**Objective:** Test new process with live data, refine procedures, validate outcomes

**Key activities:**
- **Pilot close execution**
  - Run full close cycle using new process (use actual data from recent period)
  - Execute GL reconciliation using new automation (note what works, what breaks)
  - Test approval workflow with new streamlined design
  - Track time spent per task (measure actual vs. target)

- **Issue identification & resolution**
  - Log issues (data quality problems, process gaps, tool limitations)
  - Prioritize (critical = blocks close, major = adds time, minor = nice-to-fix)
  - Fix critical/major issues before next cycle
  - Document workarounds for known issues

- **Procedure refinement**
  - Update close procedures based on pilot learnings
  - Clarify exception handling (what happens when automation fails?)
  - Refine role definitions based on actual work observed

- **Training & readiness**
  - Train full close team on new process (not just pilot participants)
  - Conduct dry-run close exercise with full team
  - Validate team confidence level

- **Governance & escalation**
  - Confirm steering committee sign-off to proceed to full implementation
  - Document risks and mitigations
  - Finalize go-live readiness checklist

**Deliverables:**
- Pilot close results (actual time by task, % automation achieved, issues log)
- Refined procedures (based on pilot learnings)
- Updated GL reconciliation rules (based on exceptions encountered)
- Training completion reports (% of team trained, competency assessment)
- Go/No-go decision document (readiness for full deployment)

**Client commitments:**
- **Availability**: Close owner 100% (pilot close cycle), GL team 100% (pilot close cycle)
- **Decisions**: Steering committee approval to proceed with full implementation
- **Resources**: Full close team participation in dry-run exercise
- **Timeline**: 4 weeks (Weeks 11-14) — one pilot cycle + refinement

**Decision gate (End of Week 14):**
- ✓ Did we achieve target close calendar (6 days)? If not, is the improvement directional?
- ✓ Are critical issues resolved? Are remaining issues acceptable workarounds?
- ✓ Is team confident in new process? Any holdouts we need to address?
- ✓ Proceed to full implementation or run another pilot cycle?

---

### Phase 4: Deploy & Stabilize (Weeks 15-17, ongoing support)

**Objective:** Execute full close with new process, support team transition, handoff to operations

**Key activities:**
- **Full close deployment**
  - Execute full close cycle (all regions, all accounts, all transactions) with new process
  - Run close with 24/7 support team available
  - Monitor and log issues in real-time
  - Implement fixes and workarounds as needed

- **Ongoing support**
  - Answer questions from close team
  - Troubleshoot issues
  - Provide just-in-time training as needed
  - Refine procedures based on real-world execution

- **Performance tracking**
  - Measure actual close calendar (target: 6 days)
  - Calculate automation rate achieved (target: GL recon drops from 45% to <10% of close effort)
  - Identify staff that adapted well vs. those struggling
  - Document any training needs

- **Transition to operations**
  - Document final procedures (what we're committing to going forward)
  - Identify backup resources for critical roles
  - Create ongoing training and onboarding materials
  - Define escalation path for exceptions

- **Continuous improvement**
  - Identify additional automation opportunities (manual tasks that weren't in Phase 2 scope)
  - Plan Phase 5 (if applicable): Advanced optimization (e.g., "can we get to 4-day close?")
  - Document lessons learned

**Deliverables:**
- Go-live execution report (actual close calendar, automation rate achieved, issues handled)
- Final close procedures (locked in; baseline for future training)
- Staffing model (roles, FTE allocation, backup coverage)
- Continuous improvement roadmap (future opportunities)
- Lessons learned document (what worked, what would we do differently)

**Client commitments:**
- **Availability**: Close owner 100% (deployment month), GL team 100% (deployment month)
- **Support model**: Steering committee available for escalations; business continuity plan in place
- **Resources**: Backup procedures in place in case of system/data issues
- **Timeline**: 3 weeks (Weeks 15-17) for first close, ongoing support as needed

**Post-deployment support (Weeks 18+):**
- Resolve residual issues
- Optimize based on early learnings
- Plan Phase 5 or continuous improvement activities

---

## Customization examples

### For GBS / operating model transformation (longer, broader scope)

**Phase 1:** Diagnose & Design (Weeks 1-6)
- Current-state organizational structure, process, cost model
- Benchmarking against GBS models
- Target-state design (centralized vs. regional hubs, nearshore/offshore)

**Phase 2:** Organize & Build (Weeks 7-16)
- Create new organizational structure
- Hire/transition resources to GBS
- Configure processes and systems for shared services
- Establish GBS governance and SLAs

**Phase 3:** Transition & Stabilize (Weeks 17-24)
- Migrate processes to GBS in waves
- Monitor quality and cost
- Refine processes based on early execution
- Finalize staffing and handoff

**Phase 4:** Optimize (Weeks 25+)
- Measure GBS cost per transaction
- Identify automation opportunities in GBS
- Plan continuous improvement

---

### For FP&A transformation (different pace, different deliverables)

**Phase 1:** Diagnose & Design (Weeks 1-4)
- Current planning process, tools, accuracy
- Forecast review and root cause of variances
- Benchmark FP&A maturity
- Design future-state planning process and system architecture

**Phase 2:** Configure & Build (Weeks 5-10)
- Build new planning system/tools
- Configure forecast models (drivers, scenarios)
- Design new governance (planning calendar, review cycles)
- Build self-service analytics

**Phase 3:** Pilot & Test (Weeks 11-14)
- Run pilot forecast cycle (1-2 months of data)
- Test scenario modeling
- Refine models based on results

**Phase 4:** Deploy & Optimize (Weeks 15+)
- Roll out new planning process for next quarterly forecast
- Monitor accuracy and cycle time
- Add scenarios/analytics based on user demand

---

## Decision gates: When to pause or redirect

**Decision gate criteria (go/no-go/proceed-with-modifications):**

✓ **GO** — Proceed to next phase as planned
- Key deliverables complete and approved
- Risks identified and mitigation plans in place
- Team confidence high
- Client sponsors aligned

⚠️ **PROCEED WITH MODIFICATIONS** — Next phase continues but with changes
- Some deliverables incomplete; can be caught up in next phase
- One major risk identified but mitigation plan credible
- Team has questions; need one more design review
- Client sponsor alignment requires one more discussion

❌ **NO-GO** — Pause; reassess approach
- Critical deliverable incomplete (e.g., data quality assessment shows major issues)
- Major risk identified with no mitigation plan
- Team or client sponsor fundamentally disagree on approach
- Business disruption makes continuation risky (e.g., major system outage, leadership change)

---

## Client commitments summary

| Phase | Client FTE Commitment | Key Decisions | Timeline |
|-------|----------------------|---------------|----------|
| **Phase 1: Diagnose & Design** | Close owner 50%, GL mgr 25%, Sample controllers | Agree on root causes, approve design, proceed vs. quick-wins only | 4 weeks |
| **Phase 2: Build & Configure** | Close owner 75%, GL mgr 50%, IT support | Approve GL rules, resolve data quality issues, proceed to pilot | 6 weeks |
| **Phase 3: Pilot & Stabilize** | Close owner 100%, GL team 100% | Evaluate pilot results, approve procedures, proceed to deployment | 4 weeks |
| **Phase 4: Deploy** | Close owner 100%, GL team 100%, Support available | Monitor deployment, resolve issues, handoff to operations | 3 weeks |

**Total: 17 weeks (4 months) for close acceleration; 6-12 months for GBS or FP&A transformations**

