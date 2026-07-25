"use client";

import { Download, FileText, Upload } from "lucide-react";
import Link from "next/link";

// ── Template definitions ───────────────────────────────────────────────────────

interface CSVTemplate {
  agent: string;
  file: string;
  description: string;
  columns: string;
  content: string;
}

const TEMPLATES: CSVTemplate[] = [
  // ── CFO ──────────────────────────────────────────────────────────────────────
  {
    agent: "CFO",
    file: "cfo_transactions.csv",
    description: "Financial transactions for P&L, cashflow and forecast analysis",
    columns: "date, description, amount_cents, type, category",
    content: `date,description,amount_cents,type,category
2024-01-05,SaaS subscription revenue,500000,revenue,saas
2024-01-10,Cloud hosting bill,-120000,expense,infrastructure
2024-01-15,Enterprise deal — Acme Corp,2000000,revenue,enterprise
2024-01-20,Payroll — January,-850000,expense,payroll
2024-01-25,Office lease payment,-150000,expense,facilities
2024-02-05,SaaS subscription revenue,520000,revenue,saas
2024-02-10,Cloud hosting bill,-130000,expense,infrastructure
2024-02-15,Marketing campaign spend,-200000,expense,marketing
2024-02-20,Payroll — February,-870000,expense,payroll
2024-02-28,New enterprise deal,3000000,revenue,enterprise`,
  },

  // ── CTO ──────────────────────────────────────────────────────────────────────
  {
    agent: "CTO — Cloud Billing",
    file: "cto_cloud_billing.csv",
    description: "Cloud infrastructure costs by service and environment",
    columns: "service, cost, environment, region, team",
    content: `service,cost,environment,region,team
EC2,1200,prod,eu-west-1,platform
RDS,800,prod,eu-west-1,data
S3,150,prod,eu-west-1,platform
Lambda,80,prod,eu-west-1,backend
ElastiCache,300,prod,eu-west-1,backend
EC2,400,staging,eu-west-1,platform
RDS,200,staging,eu-west-1,data
EC2,600,dev,eu-west-1,engineering`,
  },
  {
    agent: "CTO — Incidents",
    file: "cto_incidents.csv",
    description: "Production incidents for MTTR and reliability analysis",
    columns: "id, severity, title, created_at, resolved_at, team, root_cause",
    content: `id,severity,title,created_at,resolved_at,team,root_cause
INC-001,P1,Database connection pool exhausted,2024-01-08 14:00,2024-01-08 16:30,platform,config_error
INC-002,P2,API gateway 502 errors spike,2024-01-15 09:00,2024-01-15 11:00,backend,deployment
INC-003,P1,Payment processing outage,2024-02-03 18:00,2024-02-03 20:15,payments,vendor_issue
INC-004,P3,Slow dashboard load times,2024-02-10 10:00,2024-02-10 14:00,frontend,query_optimization
INC-005,P2,Auth service degradation,2024-03-01 08:00,2024-03-01 09:30,security,cert_expiry`,
  },
  {
    agent: "CTO — Sprints",
    file: "cto_sprints.csv",
    description: "Sprint velocity data for engineering throughput analysis",
    columns: "sprint, committed, completed, team, start_date",
    content: `sprint,committed,completed,team,start_date
Sprint 1,20,18,backend,2024-01-08
Sprint 1,15,15,frontend,2024-01-08
Sprint 2,22,19,backend,2024-01-22
Sprint 2,16,14,frontend,2024-01-22
Sprint 3,20,20,backend,2024-02-05
Sprint 3,18,16,frontend,2024-02-05`,
  },

  // ── CMO ──────────────────────────────────────────────────────────────────────
  {
    agent: "CMO — Campaigns",
    file: "cmo_campaigns.csv",
    description: "Marketing campaign performance for ROI and CAC analysis",
    columns: "campaign, channel, spend, leads, conversions, revenue",
    content: `campaign,channel,spend,leads,conversions,revenue
Q1 Google Ads,paid_search,15000,420,38,95000
Q1 LinkedIn,social,8000,180,12,48000
Q1 Email Nurture,email,2000,850,45,67500
Q1 Content SEO,organic,3000,1200,28,56000
Q2 Google Ads,paid_search,18000,510,44,110000
Q2 LinkedIn,social,10000,220,16,64000`,
  },

  // ── COO ──────────────────────────────────────────────────────────────────────
  {
    agent: "COO — Processes",
    file: "coo_processes.csv",
    description: "Business process efficiency metrics",
    columns: "process, team, cycle_time, throughput, wip, capacity",
    content: `process,team,cycle_time,throughput,wip,capacity
Order Fulfillment,Warehouse,2.5,120,18,150
Customer Onboarding,Sales,7.0,25,35,30
Technical Support,Support,4.2,80,22,100
Invoice Processing,Finance,1.5,200,15,250
Product Deployment,Engineering,3.0,40,12,50`,
  },
  {
    agent: "COO — Resources",
    file: "coo_resources.csv",
    description: "Team resource utilization and output metrics",
    columns: "team, headcount, utilization, output, capacity",
    content: `team,headcount,utilization,output,capacity
Engineering,25,0.92,450,500
Sales,10,0.75,200,250
Support,15,1.15,280,280
Marketing,8,0.80,160,200
Finance,6,0.70,120,180
Operations,12,0.88,240,275`,
  },
  {
    agent: "COO — SLA / Tickets",
    file: "coo_sla_tickets.csv",
    description: "Customer support tickets for SLA and NPS analysis",
    columns: "ticket_id, priority, created_at, resolved_at, nps_score, category",
    content: `ticket_id,priority,created_at,resolved_at,nps_score,category
T001,p1,2024-01-01 09:00:00,2024-01-01 12:00:00,8,billing
T002,p2,2024-01-02 10:00:00,2024-01-03 08:00:00,6,technical
T003,p1,2024-01-05 14:00:00,2024-01-05 16:30:00,9,account
T004,p3,2024-01-08 11:00:00,2024-01-10 15:00:00,5,feature_request
T005,p2,2024-01-10 09:00:00,2024-01-11 10:00:00,7,technical`,
  },

  // ── CHRO ─────────────────────────────────────────────────────────────────────
  {
    agent: "CHRO — Headcount",
    file: "chro_headcount.csv",
    description: "Employee roster for headcount and org structure analysis",
    columns: "employee_id, name, department, level, role, location, fte, start_date, status",
    content: `employee_id,name,department,level,role,location,fte,start_date,status
EMP001,Alice Chen,Engineering,L4,Senior Engineer,Istanbul,1.0,2021-03-15,active
EMP002,Bob Kim,Engineering,L3,Engineer,Istanbul,1.0,2022-07-01,active
EMP003,Carol Davis,Product,L5,Principal PM,Remote,1.0,2020-01-10,active
EMP004,Dan Ortiz,Sales,L2,Account Executive,Ankara,1.0,2023-02-28,active
EMP005,Eva Müller,HR,L3,HR Business Partner,Istanbul,1.0,2021-09-20,active
EMP006,Frank Lee,Marketing,L3,Marketing Manager,Istanbul,1.0,2022-04-11,active
EMP007,Grace Park,Finance,L4,Finance Lead,Istanbul,1.0,2020-08-01,active`,
  },
  {
    agent: "CHRO — Attrition",
    file: "chro_attrition.csv",
    description: "Historical departures for attrition risk analysis",
    columns: "employee_id, department, level, role, tenure_years, departure_date, departure_type, reason, replaced",
    content: `employee_id,department,level,role,tenure_years,departure_date,departure_type,reason,replaced
EMP010,Engineering,L3,Engineer,1.5,2024-01-15,voluntary,better_offer,no
EMP011,Sales,L2,Account Executive,0.8,2024-02-01,voluntary,compensation,yes
EMP012,Product,L4,Senior PM,3.2,2024-02-20,voluntary,career_growth,no
EMP013,Engineering,L5,Staff Engineer,4.1,2024-03-10,voluntary,better_offer,no
EMP014,Marketing,L2,Marketing Analyst,1.1,2024-03-25,involuntary,performance,yes`,
  },
  {
    agent: "CHRO — Compensation",
    file: "chro_compensation.csv",
    description: "Salary and benefits data for compensation benchmarking",
    columns: "employee_id, department, level, role, base_salary, equity_annual, benefits_annual, market_rate, location",
    content: `employee_id,department,level,role,base_salary,equity_annual,benefits_annual,market_rate,location
EMP001,Engineering,L4,Senior Engineer,95000,15000,12000,105000,Istanbul
EMP002,Engineering,L3,Engineer,72000,8000,10000,78000,Istanbul
EMP003,Product,L5,Principal PM,115000,20000,14000,120000,Remote
EMP004,Sales,L2,Account Executive,55000,0,8000,58000,Ankara
EMP005,HR,L3,HR Business Partner,68000,5000,10000,70000,Istanbul`,
  },

  // ── Compliance ────────────────────────────────────────────────────────────────
  {
    agent: "Compliance — Policies",
    file: "compliance_policies.csv",
    description: "Policy inventory for compliance management",
    columns: "policy, severity, status, last_review, owner, category",
    content: `policy,severity,status,last_review,owner,category
Data Classification Policy,high,active,2022-01-15,CISO,data_governance
Access Control Policy,critical,active,2023-06-01,IT Security,security
Incident Response Plan,high,active,2024-01-10,IT Security,security
Password Policy,medium,active,2022-11-20,IT,security
Data Retention Policy,high,active,2021-08-01,Legal,data_governance
Business Continuity Plan,critical,active,2024-02-01,Operations,continuity`,
  },
  {
    agent: "Compliance — Violations",
    file: "compliance_violations.csv",
    description: "Compliance violations for remediation tracking",
    columns: "violation, policy_id, severity, date_found, due_date, remediation_status, responsible_party, framework",
    content: `violation,policy_id,severity,date_found,due_date,remediation_status,responsible_party,framework
Unencrypted S3 bucket,POL-001,critical,2024-01-10,2024-01-17,open,DevOps,SOC2
Missing MFA on admin accounts,POL-002,critical,2024-02-01,2024-02-08,in progress,IT Security,SOC2
Excessive user privileges,POL-003,high,2024-01-05,2024-02-05,open,IAM Team,ISO27001
Outdated SSL certificate,POL-004,medium,2024-03-01,2024-03-31,resolved,DevOps,PCI-DSS`,
  },
  {
    agent: "Compliance — Regulations",
    file: "compliance_regulations.csv",
    description: "Regulatory requirements coverage tracking",
    columns: "regulation, requirement, compliance_status, last_audit, next_audit, control_owner, risk_level",
    content: `regulation,requirement,compliance_status,last_audit,next_audit,control_owner,risk_level
SOC2,CC6.1 Logical Access,compliant,2024-01-15,2025-01-15,IT Security,high
SOC2,CC7.1 System Monitoring,non-compliant,2024-01-15,2025-01-15,Platform,high
ISO 27001,A.9.1 Access Control Policy,compliant,2023-06-01,2024-06-01,IT Security,high
GDPR,Article 17 Right to Erasure,non-compliant,2024-03-01,2025-03-01,Data Team,critical`,
  },

  // ── Risk ─────────────────────────────────────────────────────────────────────
  {
    agent: "Risk — Register",
    file: "risk_register.csv",
    description: "Enterprise risk register for scoring and heatmap",
    columns: "risk_id, category, description, likelihood, impact, owner, status, mitigation",
    content: `risk_id,category,description,likelihood,impact,owner,status,mitigation
R001,operational,System outage during peak hours,3,5,CTO,open,Redundancy plan in progress
R002,financial,FX exposure on USD payables,4,4,CFO,open,Hedging strategy being evaluated
R003,compliance,GDPR data retention gaps,3,4,Legal,mitigated,Policy updated Q1
R004,strategic,Key person dependency — CTO,2,5,CEO,open,Documentation and hiring plan
R005,cyber,Phishing attack susceptibility,4,3,CISO,open,Security training Q2`,
  },
  {
    agent: "Risk — Loss Events",
    file: "risk_loss_events.csv",
    description: "Loss event log for incident cost tracking",
    columns: "date, category, description, gross_loss, recovery, root_cause, status",
    content: `date,category,description,gross_loss,recovery,root_cause,status
2024-01-15,operational,Payment gateway downtime (4h),15000,0,vendor_outage,closed
2024-02-03,cyber,Phishing attack credential theft,8000,2000,human_error,closed
2024-02-20,operational,Data migration error 200 records,5000,5000,process_failure,closed
2024-03-05,financial,FX loss on EUR invoice,12000,0,market_risk,closed
2024-03-18,operational,Warehouse mis-shipment 50 orders,6500,3000,process_failure,open`,
  },
  {
    agent: "Risk — KRIs",
    file: "risk_kris.csv",
    description: "Key Risk Indicators with threshold monitoring",
    columns: "name, category, current_value, threshold_red, threshold_amber, unit, trend, owner",
    content: `name,category,current_value,threshold_red,threshold_amber,unit,trend,owner
System Uptime,operational,99.2,99.5,99.8,percent,stable,CTO
SLA Breach Rate,operational,18,10,15,percent,increasing,COO
Cash Runway,financial,8,6,9,months,stable,CFO
Attrition Rate,hr,22,20,15,percent,increasing,CHRO
Open Critical Vulnerabilities,cyber,7,5,3,count,increasing,CTO
Compliance Coverage,compliance,88,80,90,percent,improving,Legal`,
  },

  // ── Internal Audit ────────────────────────────────────────────────────────────
  {
    agent: "Internal Audit — Findings",
    file: "audit_findings.csv",
    description: "Audit findings for remediation tracking",
    columns: "finding_id, title, severity, status, due_date, owner, category, remediation_status",
    content: `finding_id,title,severity,status,due_date,owner,category,remediation_status
F001,Unencrypted database backup,critical,open,2024-02-15,IT Security,data_security,in_progress
F002,Segregation of duties violation in finance,high,open,2024-03-01,Finance,access_control,not_started
F003,Missing disaster recovery plan,high,closed,2024-01-20,Operations,business_continuity,completed
F004,Weak password policy enforcement,medium,open,2024-03-10,IT,identity_management,in_progress
F005,Vendor contract review process gap,medium,open,2024-02-28,Procurement,third_party_risk,not_started`,
  },
  {
    agent: "Internal Audit — Controls",
    file: "audit_controls.csv",
    description: "Control effectiveness assessment data",
    columns: "control_id, name, category, design_effectiveness, operating_effectiveness, last_tested, owner",
    content: `control_id,name,category,design_effectiveness,operating_effectiveness,last_tested,owner
C001,Firewall rule review,it_security,85,80,2024-01-15,CTO
C002,Segregation of duties matrix,access_control,90,75,2023-11-20,CFO
C003,Data backup verification,data_security,95,90,2024-02-01,IT Manager
C004,Vendor risk assessment,third_party,80,65,2023-10-05,Procurement
C005,Change management approval,it_operations,85,85,2024-01-25,CTO`,
  },
  {
    agent: "Internal Audit — Coverage",
    file: "audit_coverage.csv",
    description: "Audit universe coverage tracking",
    columns: "unit_name, category, last_audit, frequency, risk_rating, scheduled_next",
    content: `unit_name,category,last_audit,frequency,risk_rating,scheduled_next
IT Infrastructure,technology,2023-06-15,annual,high,2024-06-15
Accounts Payable,finance,2023-09-01,annual,medium,2024-09-01
HR Payroll,hr,2024-01-10,annual,medium,2025-01-10
Third-Party Vendors,procurement,2023-03-20,annual,high,2024-03-20
Physical Security,operations,2023-08-15,annual,low,2024-08-15`,
  },
];

// ── Agent grouping ────────────────────────────────────────────────────────────

const AGENT_COLORS: Record<string, string> = {
  CFO:             "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  CTO:             "bg-blue-500/10 text-blue-500 border-blue-500/20",
  CMO:             "bg-purple-500/10 text-purple-500 border-purple-500/20",
  COO:             "bg-orange-500/10 text-orange-500 border-orange-500/20",
  CHRO:            "bg-pink-500/10 text-pink-500 border-pink-500/20",
  Compliance:      "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
  Risk:            "bg-red-500/10 text-red-500 border-red-500/20",
  "Internal Audit":"bg-indigo-500/10 text-indigo-500 border-indigo-500/20",
};

function agentKey(agent: string): string {
  return agent.split(" — ")[0];
}

// ── Download helper ───────────────────────────────────────────────────────────

function downloadCSV(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Template Card ─────────────────────────────────────────────────────────────

function TemplateCard({ template }: { template: CSVTemplate }) {
  const key   = agentKey(template.agent);
  const color = AGENT_COLORS[key] ?? "bg-muted text-muted-foreground border-border";

  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-3 hover:border-primary/40 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase ${color}`}>
              {key}
            </span>
            <span className="text-sm font-medium">
              {template.agent.includes(" — ") ? template.agent.split(" — ")[1] : ""}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">{template.description}</p>
        </div>
      </div>

      <div className="rounded bg-muted/40 px-2 py-1.5">
        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-0.5">Sütunlar</p>
        <p className="font-mono text-xs text-muted-foreground leading-relaxed">{template.columns}</p>
      </div>

      <button
        onClick={() => downloadCSV(template.file, template.content)}
        className="flex items-center justify-center gap-2 rounded border border-border bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={`${template.file} dosyasını indir`}
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        {template.file}
      </button>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function TemplatesPage() {
  // Group templates by agent key
  const grouped = TEMPLATES.reduce<Record<string, CSVTemplate[]>>((acc, t) => {
    const k = agentKey(t.agent);
    if (!acc[k]) acc[k] = [];
    acc[k].push(t);
    return acc;
  }, {});

  function downloadAll() {
    TEMPLATES.forEach((t) => downloadCSV(t.file, t.content));
  }

  return (
    <main className="mx-auto max-w-screen-xl space-y-8 p-4 sm:p-6 lg:p-8">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <FileText className="h-6 w-6 text-primary" aria-hidden="true" />
          <div>
            <h1 className="text-xl font-bold">CSV Şablonları</h1>
            <p className="text-sm text-muted-foreground">
              Her agent için örnek CSV dosyalarını indirin ve kendi verilerinize uyarlayın.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/upload"
            className="flex items-center gap-2 rounded border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
          >
            <Upload className="h-4 w-4" aria-hidden="true" />
            Veri Yükle
          </Link>
          <button
            onClick={downloadAll}
            className="flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            Tümünü İndir ({TEMPLATES.length} dosya)
          </button>
        </div>
      </div>

      {/* Nasıl kullanılır */}
      <div className="rounded-lg border border-primary/20 bg-primary/5 p-4 text-sm">
        <p className="mb-2 font-medium text-foreground">Nasıl kullanılır?</p>
        <ol className="space-y-1 text-muted-foreground list-decimal list-inside">
          <li>İhtiyacınız olan domain şablonunu indirin (örn. CHRO → Çalışan Listesi)</li>
          <li>Şablonu kendi verilerinizle doldurun — sütun adlarını değiştirmeyin</li>
          <li><Link href="/upload" className="text-primary underline underline-offset-2">Veri Yükleme</Link> sayfasında banka ekstresini ve domain dosyalarını yükleyin</li>
          <li>AI agent'lar tüm verileri birleştirerek kapsamlı analiz üretecek</li>
        </ol>
      </div>

      {/* Şablon grupları */}
      {Object.entries(grouped).map(([agentName, templates]) => {
        const color = AGENT_COLORS[agentName] ?? "bg-muted text-muted-foreground border-border";
        return (
          <section key={agentName}>
            <div className="mb-3 flex items-center gap-3">
              <span className={`rounded border px-2.5 py-1 text-xs font-semibold uppercase ${color}`}>
                {agentName}
              </span>
              <span className="text-xs text-muted-foreground">
                {templates.length} şablon
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {templates.map((t) => (
                <TemplateCard key={t.file} template={t} />
              ))}
            </div>
          </section>
        );
      })}
    </main>
  );
}
