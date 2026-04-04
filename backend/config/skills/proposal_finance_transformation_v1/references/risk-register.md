# Risk Register — Finance-Specific Risks & Mitigations

Build a credible risk register that shows you understand finance transformation constraints, not generic project risks.

---

## Finance-Specific Risks by Engagement Type

### Close Acceleration Risks

#### Risk 1: Data Quality Blocks Automation Opportunity

**Description:** GL reconciliation cannot be automated if subledger/GL mapping is incomplete or if account hierarchies are inconsistent.

**Impact:** 
- If 15% of accounts are unmapped, automation benefit drops from 35% to 20% of close effort
- Close calendar improvement limited to 9 days instead of target 6 days
- Require extended data remediation (2-4 week delay in implementation timeline)
- Cost impact: $200K-$400K in data cleanse effort

**Probability:** Medium (60% of finance environments have >10% data quality issues)

**Evidence:**
- Initial assessment plan includes data quality audit (Week 1)
- If critical issues found, plan 2-week data remediation sprint before automation build

**Mitigation:**
1. **Pre-transformation data cleanse (Weeks 5-7)** — Fix unmapped accounts, reconcile GL hierarchies
2. **Establish GL data governance** — Going forward, enforce account mapping rules, prevent duplicates
3. **Create GL reconciliation validation scripts** — Automated checks to identify new problems early
4. **Escalation path** — If data quality blocks automation, pivot to enhanced manual process (not automation), still achieves 3-day improvement

**Owner:** Finance + IT

**Timeline to mitigate:** 2-3 weeks before full automation deployment

---

#### Risk 2: Staff Resistance to Elimination of Approval Steps

**Description:** Current close has 6-8 approval steps; some approvers have organizational power and resist loss of visibility/control.

**Impact:**
- Late adoption; people bypass new process, reverting to old approvals
- Quality issues if manual review gates are removed without controls
- Morale issues; approvers feel demoted
- Close calendar improvement stalls; can't achieve full 6-day target
- Potential staff turnover (1-2 key people)

**Probability:** High (80% of finance teams resist process reduction)

**Evidence:**
- Stakeholder interviews (Phase 1) will identify approvers who feel loss of control
- Training completion rates will signal adoption resistance

**Mitigation:**
1. **Organizational change management program**
   - Position as role elevation, not elimination (people move from approval to exception handling)
   - Clarify new responsibilities (exception approvers, variance investigators, quality reviewers)
   
2. **Reskilling program**
   - Offer internal mobility (transactional close staff → operational finance roles)
   - Provide cross-training in related finance functions (FP&A support, cash management)
   
3. **Incentive alignment**
   - Tie CFO metrics to close speed (make it a KPI)
   - Include close performance in individual scorecards (staff bonus tied to on-time close)
   
4. **Communication strategy**
   - Early announcement of new organization structure
   - Celebrate quick wins (e.g., "We cut close from 12 to 9 days in Phase 1")
   - Share benefits clearly (CFO can make decisions faster, staff can work on higher-value activities)

5. **Phased transition** (not big bang)
   - Week 1: Remove 1 approval step, track adoption
   - Week 2: Remove second step, measure impact
   - Week 3-4: Implement final changes, by then team has accepted first changes

**Owner:** CFO + HR + Project Manager

**Timeline to address:** Ongoing throughout project; critical in Weeks 4-6

---

#### Risk 3: Year-End Audit Cycle Blocks Implementation

**Description:** Close transformation work + annual financial audit creates competing demands for finance staff time.

**Impact:**
- Peak workload: close staff, GL managers, finance leadership all overloaded during audit period (Oct-Dec)
- Can't run pilot close during busy season; delays implementation by 1-2 months
- Audit timeline pressure may force extension of old manual processes
- Staff burnout if asked to do transformation + audit simultaneously
- System changes can't be implemented near year-end (audit control concerns)

**Probability:** Very High (100% for companies with Dec 31 year-end)

**Evidence:**
- Client fiscal year-end will be identified in Phase 1
- Audit timeline/workload documented during current-state assessment

**Mitigation:**
1. **Phase project around audit timeline**
   - Design/build (Q1): No audit pressure; can focus on transformation
   - Pilot (Q2-Q3): No audit conflicts; can test new process with full team focus
   - Deploy (Q4 post-audit or Q1): After audit pressure is off; implementation support available
   
2. **Separate audit team from close team** (if possible)
   - Assign different staff to audit support vs. transformation
   - Design close changes to minimize audit impact (controls shouldn't be removed, just streamlined)
   
3. **IT freeze management**
   - Identify IT change freeze windows (30-45 days before/after audit)
   - Schedule any system changes outside freeze window
   - Document control changes for audit transparency
   
4. **Escalation path**
   - If audit timeline changes (early/late), reassess project schedule
   - Define what work is essential vs. nice-to-have for go-live (if timeline compresses)
   - Plan extended support period if launch near year-end anyway

**Owner:** CFO + IT + External Auditors

**Timeline to address:** Identified in Phase 1; mitigated in Phase 2 schedule

---

#### Risk 4: GL System Architecture Limits Real-Time Reconciliation

**Description:** If using SAP, GL only refreshes to warehouse nightly (batch job). Real-time GL reconciliation assumed in hypothesis but technically not feasible.

**Impact:**
- Real-time reconciliation target may not be achievable; need alternative approach
- Delays automation deployment (requires workaround design)
- GL refresh delay (8-12 hours) means close team can't start reconciliation until next morning
- Close calendar improvement limited; real-time benefit impossible

**Probability:** Medium (30% of SAP environments have this constraint)

**Evidence:**
- IT system architecture assessment (Phase 1, Week 2)
- SAP configuration review identifies GL refresh batches and schedule

**Mitigation:**
1. **Early tech assessment (Week 1-2)**
   - Confirm GL refresh frequency and timing
   - If nightly refresh, design same-day manual reconciliation (instead of real-time)
   - If real-time possible, plan API implementation
   
2. **Alternative approach (if real-time not feasible)**
   - Same-day GL refresh (shift batch job from 2am to 8am)
   - Close staff starts GL reconciliation at 9am (with previous day's GL)
   - Still achieves faster close; just not real-time

3. **Technical solution (if budget allows)**
   - Implement GL replication (real-time copy of GL to separate database)
   - Reconciliation runs against replicated GL, not production
   - Reconciliation results posted back to production system

**Owner:** IT + Finance Tech

**Timeline to address:** Weeks 1-2; decision by end of Phase 1 design

---

### FP&A Transformation Risks

#### Risk: Forecast Model Complexity Exceeds Build Capacity

**Description:** Planning model design assumes ability to model revenue, COGS, operating expenses by cost center and product line with variable relationships. Actual system capabilities or data availability may not support this complexity.

**Impact:**
- Model builds take longer than 6 weeks (spills into Phase 3)
- Simplified model deployed (fewer variables); forecast accuracy doesn't improve as expected
- Training delayed; users lack confidence in results
- Go-live pushed back 4-8 weeks

**Probability:** Medium-High (65% of planning implementations encounter scope/complexity issues)

**Mitigation:**
1. **Phased model deployment**
   - Phase 1: Deploy revenue forecast (simplest, fastest value)
   - Phase 2: Add COGS variance (requires cost accounting structure)
   - Phase 3: Add OpEx waterfall (most complex; requires cost center data)

2. **Early data assessment (Week 1-2)**
   - Confirm data availability and quality for all model inputs
   - Identify data gaps; plan data remediation if needed
   - Simplify model scope if data constraints exist

3. **Limit initial scenario complexity**
   - Start with 2-3 base scenarios (bull case, base, bear)
   - Add custom scenarios post-launch based on user demand
   - Avoid "build everything at once" trap

**Owner:** FP&A Lead + IT

---

### GBS / Operating Model Risks

#### Risk: Shared Services Center Ramp-Up Delays

**Description:** Transition of transactional processes to new GBS center (internal or nearshore) requires staff hiring, training, and ramp-up. New team may take 3-6 months to reach full productivity.

**Impact:**
- Cost benefits delayed 3-6 months (productivity ramp lower than planned)
- Quality issues during ramp (higher error rates, additional rework)
- First few months of cost higher than budget (duplication: legacy + GBS)
- Staffing plan must account for dual running (legacy org can't be cut immediately)

**Probability:** Very High (90% of GBS transitions encounter ramp delays)

**Mitigation:**
1. **Early GBS team buildout (Phase 2)**
   - Hire GBS staff 2-3 months before transition
   - On-board and train before go-live
   - Start with shadow/observation work (low-risk, high-learning)

2. **Phased transition** (not big bang)
   - Week 1-2: AP invoicing only (simplest process)
   - Week 3: Add GL, AR (once GBS team comfortable)
   - Week 4+: Remaining processes
   - Reduces risk per phase; allows quality/productivity checks before expanding

3. **Productivity ramp planning**
   - Budget assumes 50% productivity Month 1, 75% Month 2, 90% Month 3, 100% Month 4
   - Don't cut legacy staffing until Month 4
   - Plan 6-month transition; don't expect full savings in Year 1

4. **Quality assurance**
   - 100% transaction inspection first 30 days
   - Spot checks 50% of transactions Month 2
   - Normal audit controls by Month 3
   - Escalation path if quality fails

**Owner:** GBS Lead + HR + PMO

---

## Risk Register Template

Use this table to document all identified risks:

| Risk Category | Risk Description | Probability | Impact | Overall Severity | Mitigation Strategy | Owner | Timeline |
|---|---|---|---|---|---|---|---|
| **Data Quality** | GL unmapped accounts block automation | Medium (60%) | High | **RED** | Pre-transformation data cleanse (2 wks) | Finance + IT | Weeks 5-7 |
| **Organizational** | Staff resist approval elimination | High (80%) | Medium | **ORANGE** | Change mgmt program + reskilling | CFO + HR | Weeks 4-8 |
| **Calendar** | Year-end audit blocks implementation | Very High (100%) | High | **RED** | Phase project around audit timeline | PMO + CFO | Phase 1 |
| **Technical** | SAP GL refresh blocks real-time recon | Medium (30%) | Medium | **ORANGE** | Early tech assessment, plan alternative | IT | Weeks 1-2 |

---

## Red flags: Risks to avoid

❌ **Generic risks that apply to any project:**
- "Communication risk"
- "Resource availability risk"
- "Budget overrun risk"
- "Schedule risk"

❌ **Unsubstantiated risks without evidence:**
- "Technology risks may arise"
- "Unforeseen challenges could emerge"
- "External factors may impact project"

❌ **Vague mitigations:**
- "Daily communication"
- "Strong governance"
- "Close monitoring"

✅ **Finance-specific risks with concrete mitigations:**
- "GL data quality (15% unmapped) blocks automation; mitigate with 2-week pre-transformation data cleanse"
- "Staff resistance to approval elimination; mitigate with reskilling program + incentive alignment"
- "Audit cycle conflicts; mitigate by phasing project around audit timeline"

---

## Risk register maintenance

**Update frequency:** Weekly during active phases (1-4), monthly during planning phases

**At each steering committee:**
- Review current risks (any changes?)
- Add newly identified risks
- Close risks where mitigation complete (document why closed)
- Escalate "red" risks to sponsor if mitigation inadequate

**Pre-decision gate:**
- Are all "red" risks mitigated? If not, don't proceed
- Are "orange" risks acceptable? Document acceptance by sponsor
- Add contingency to timeline/budget if major risks remain

