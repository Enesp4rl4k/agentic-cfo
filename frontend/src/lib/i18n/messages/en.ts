import { brand } from "@/lib/branding";

export type MessageTree = {
  product: {
    name: string;
    tagline: string;
  };
  nav: {
    general: string;
    finance: string;
    analysis: string;
    csuite: string;
    portal: string;
    commandCenter: string;
    dashboard: string;
    upload: string;
    billing: string;
    integrations: string;
    smmm: string;
    smmmOnay: string;
  };
  commandCenter: {
    title: string;
    subtitle: string;
    generateDeck: string;
    conflicts: string;
    turkeyPackHint: string;
  };
  billing: {
    title: string;
    subtitle: string;
    monthly: string;
    yearly: string;
    currentPlan: string;
    selectPlan: string;
    redirecting: string;
    managePortal: string;
  };
  upload: {
    title: string;
    subtitle: string;
  };
  csvInput: {
    placeholder: string;
    sampleData: string;
    hide: string;
    edit: string;
    chooseFile: string;
    dropAria: string;
    dataLoaded: string;
    lineCount: string;
    clickToEdit: string;
    editWord: string;
    clearData: string;
    dropHint: string;
    dropHintActive: string;
    maxFile: string;
    closeEditor: string;
  };
  empty: {
    noRoleData: string;
    enableDemo: string;
  };
  roleDashboards: {
    ceo: {
      title: string;
      description: string;
      sections: { crossDomainRiskTimeline: string };
      body: {
        risk: string;
        currentCompanyContext: string;
        newAnalysis: string;
        analysisInputs: string;
        companyName: string;
        period: string;
        preparingAnalysis: string;
        summarizeFromCfo: string;
        runAnalysis: string;
        refreshingSummary: string;
        refreshExecutiveSummary: string;
        emptyState: string;
        synthesisFailed: string;
        unknownError: string;
        downloadBoardDeckPdf: string;
        downloadOnePagerPdf: string;
        downloading: string;
      };
    };
    cto: {
      title: string;
      description: string;
      sections: {
        infrastructureCost: string;
        technicalDebt: string;
        incidentReliability: string;
        engineeringVelocity: string;
      };
      body: {
        totalSpend: string;
        estWaste: string;
        momChange: string;
        drivers: string;
        services: string;
        topCostDrivers: string;
        debtScore: string;
        commits: string;
        contributors: string;
        churnRate: string;
        hotspotFiles: string;
        changes: string;
        busFactorRisk: string;
        total: string;
        slaBreaches: string;
        trend: string;
        trendingUp: string;
        trendingDown: string;
        stable: string;
        avgVelocity: string;
        predictability: string;
        carryover: string;
        pts: string;
        sprintCompletionRate: string;
        inputFields: {
          cloudBillingCsv: string;
          gitLog: string;
          incidentCsv: string;
          sprintCsv: string;
        };
        formHint: string;
        analyzing: string;
        runAnalysis: string;
        healthScoreHeading: string;
        healthLabels: {
          good: string;
          watch: string;
          risky: string;
          critical: string;
        };
        noData: string;
        startHeading: string;
        newAnalysis: string;
      };
    };
    cmo: {
      title: string;
      description: string;
      sections: { campaignPerformance: string; leadFunnel: string; retentionLtv: string };
      body: {
        overallRoas: string;
        roasHelp: string;
        avgAcquisitionCost: string;
        cacHelp: string;
        totalSpend: string;
        attributedRevenue: string;
        conversions: string;
        byChannel: string;
        topCampaigns: string;
        campaignsNeedingReview: string;
        spend: string;
        funnelLeads: string;
        funnelMqls: string;
        funnelSqls: string;
        funnelWon: string;
        conversion: string;
        overallConversion: string;
        avgSalesCycle: string;
        days: string;
        bottleneckStage: string;
        bySource: string;
        sourceSummary: string;
        retention30d: string;
        retention90d: string;
        monthlyChurn: string;
        avgLtv: string;
        ltvCacRatio: string;
        retentionTrend: string;
        cohortsAnalyzed: string;
        bestCohort: string;
        worstCohort: string;
        retention: string;
        trendImproving: string;
        trendDeclining: string;
        trendStable: string;
        cmoSummary: string;
        marketingHealth: string;
        growthEfficiency: string;
        topRisks: string;
        quickWins: string;
        effortLabel: string;
        companyName: string;
        period: string;
        campaignCsvLabel: string;
        funnelCsvLabel: string;
        cohortCsvLabel: string;
        validationError: string;
        analyzing: string;
        runAnalysis: string;
        csvPasteHeading: string;
        pipelineError: string;
      };
    };
    chro: {
      title: string;
      description: string;
      sections: {
        headcountOverview: string;
        attritionAnalysis: string;
        compensationAnalysis: string;
        hrHealthSummary: string;
      };
      body: {
        totalHeadcount: string;
        totalFte: string;
        newHires30d: string;
        avgTenure: string;
        yrs: string;
        netChange30d: string;
        byDepartment: string;
        avg: string;
        noAlerts: string;
        totalAttritions: string;
        voluntary: string;
        annualRate: string;
        attritionCost: string;
        topDepartureReasons: string;
        highAttritionRiskRoles: string;
        riskLabel: string;
        totalPayroll: string;
        avgSalary: string;
        equityBurn: string;
        benefitsCost: string;
        belowMarket: string;
        aboveMarket: string;
        byLevel: string;
        employees: string;
        hrScore: string;
        topHrRisks: string;
        quickWins: string;
        effort: string;
        validationError: string;
        unknownError: string;
        csvManualHeading: string;
        companyName: string;
        period: string;
        headcountCsvLabel: string;
        attritionCsvLabel: string;
        compensationCsvLabel: string;
        analyzing: string;
        runAnalysis: string;
        loadExampleData: string;
        pipelineError: string;
      };
    };
    coo: {
      title: string;
      description: string;
      sections: {
        bottlenecks: string;
        tocAnalysis: string;
        overdueTickets: string;
        atRiskTickets: string;
      };
      body: {
        cycleTimeAxis: string;
        throughputAxis: string;
        bottlenecksSeries: string;
        constraintLabels: { [key: string]: string };
        impactScore: string;
        overdueTicketsLine: string;
        trendExplanation: string;
        colTicket: string;
        colTitle: string;
        colAssigned: string;
        colRemainingHours: string;
        colUrgency: string;
        colPriority: string;
        timeExpired: string;
        near: string;
        watching: string;
        validationError: string;
        csvManualHeading: string;
        companyName: string;
        period: string;
        processesCsvLabel: string;
        slaCsvLabel: string;
        analyzing: string;
        runAnalysis: string;
        noResults: string;
        errorPrefix: string;
      };
    };
  };
  decisionBrief: {
    title: string;
    empty: string;
    rebuild: string;
    rebuildAria: string;
    reportingPeriod: string;
    vsPrior: string;
    awaitingReview: string;
    cleared: string;
    approve: string;
    approving: string;
    findings: string;
    confidence: string;
    recommendation: string;
    whatIf: string;
    runSimulation: string;
    conflicts: string;
    gateHeld: string;
    domains: { [key: string]: string };
  };
};

export const en: MessageTree = {
  product: {
    name: brand.name,
    tagline: "Your entire C-Suite, powered by AI — globally.",
  },
  nav: {
    general: "General",
    finance: "Finance",
    analysis: "Analytics",
    csuite: "C-Suite",
    portal: "Portal",
    commandCenter: "Command Center",
    dashboard: "Dashboard",
    upload: "Upload",
    billing: "Billing",
    integrations: "Integrations",
    smmm: "Turkey accounting review",
    smmmOnay: "SMMM approvals",
  },
  commandCenter: {
    title: "Executive Command Center",
    subtitle: "Multi-role management OS — depth follows your data.",
    generateDeck: "Generate board deck",
    conflicts: "Open conflicts",
    turkeyPackHint: "Turkey pack enabled",
  },
  billing: {
    title: "Choose your plan",
    subtitle: "A management operating system, from startup to enterprise.",
    monthly: "Monthly",
    yearly: "Yearly",
    currentPlan: "Current plan",
    selectPlan: "Select plan",
    redirecting: "Redirecting…",
    managePortal: "Manage subscription",
  },
  upload: {
    title: "Upload financial data",
    subtitle: "CSV, XLSX, or PDF — analyzed by the CFO pipeline.",
  },
  csvInput: {
    placeholder: "Paste CSV data or upload a file…",
    sampleData: "Sample data",
    hide: "Hide",
    edit: "Edit",
    chooseFile: "{label} — select file",
    dropAria: "{label} — upload or drag & drop file",
    dataLoaded: "Data loaded",
    lineCount: "{count} lines",
    clickToEdit: "Click to change or",
    editWord: "edit",
    clearData: "Clear data",
    dropHint: "Drag & drop a CSV file or click",
    dropHintActive: "Drop it!",
    maxFile: "Max 5 MB",
    closeEditor: "Close editor",
  },
  empty: {
    noRoleData: "No live agent results yet. Upload data or run an analysis.",
    enableDemo: "Demo mode can show sample data when enabled.",
  },
  roleDashboards: {
    ceo: {
      title: "CEO decision board",
      description: "Company priorities, progress against goals, and issues requiring executive decisions.",
      sections: { crossDomainRiskTimeline: "Cross-Domain Risk Timeline" },
      body: {
        risk: "risk",
        currentCompanyContext: "Up-to-date company context",
        newAnalysis: "New CEO analysis",
        analysisInputs: "Analysis inputs",
        companyName: "Company",
        period: "Period",
        preparingAnalysis: "Preparing analysis...",
        summarizeFromCfo: "Summarize from CFO analysis",
        runAnalysis: "Start CEO analysis",
        refreshingSummary: "Refreshing summary...",
        refreshExecutiveSummary: "Refresh executive summary",
        emptyState:
          "No live CEO results yet. Upload data and complete a CFO run, or synthesize from an active CFO job. Sample CSV paste has been removed from the default path.",
        synthesisFailed: "Synthesis failed",
        unknownError: "Unknown error",
        downloadBoardDeckPdf: "Download board deck PDF",
        downloadOnePagerPdf: "Download one-pager PDF",
        downloading: "Downloading...",
      },
    },
    cto: {
      title: "Technology & engineering",
      description: "Infrastructure costs, technical debt, incident response, and team delivery pace.",
      sections: {
        infrastructureCost: "Infrastructure Cost",
        technicalDebt: "Technical Debt",
        incidentReliability: "Incident & Reliability",
        engineeringVelocity: "Engineering Velocity",
      },
      body: {
        totalSpend: "Total Spend",
        estWaste: "Est. Waste",
        momChange: "MoM Change",
        drivers: "Drivers",
        services: "services",
        topCostDrivers: "TOP COST DRIVERS",
        debtScore: "Debt Score",
        commits: "Commits",
        contributors: "Contributors",
        churnRate: "Churn Rate",
        hotspotFiles: "HOTSPOT FILES",
        changes: "changes",
        busFactorRisk: "Bus factor risk",
        total: "Total",
        slaBreaches: "SLA Breaches",
        trend: "Trend",
        trendingUp: "Trending up",
        trendingDown: "Trending down",
        stable: "Stable",
        avgVelocity: "Avg Velocity",
        predictability: "Predictability",
        carryover: "Carryover",
        pts: "pts",
        sprintCompletionRate: "SPRINT COMPLETION RATE",
        inputFields: {
          cloudBillingCsv: "Cloud cost CSV",
          gitLog: "Git logs",
          incidentCsv: "Incident CSV",
          sprintCsv: "Sprint CSV",
        },
        formHint:
          "Paste at least one data source. All fields are optional — agents skip missing inputs.",
        analyzing: "Analyzing…",
        runAnalysis: "Run CTO Analysis",
        healthScoreHeading: "Technology health score",
        healthLabels: {
          good: "Good",
          watch: "Needs monitoring",
          risky: "Risky",
          critical: "Critical",
        },
        noData: "No data found. Check the input format.",
        startHeading: "Start CTO Analysis",
        newAnalysis: "← New analysis",
      },
    },
    cmo: {
      title: "Marketing performance",
      description: "Campaign returns, acquisition cost, funnel conversion, and customer retention.",
      sections: {
        campaignPerformance: "Campaign Performance",
        leadFunnel: "Lead Funnel",
        retentionLtv: "Customer Retention & LTV",
      },
      body: {
        overallRoas: "Overall ROAS",
        roasHelp: "Revenue generated per unit of campaign spend",
        avgAcquisitionCost: "Average acquisition cost",
        cacHelp: "Cost per acquired customer",
        totalSpend: "Total spend",
        attributedRevenue: "Attributed revenue",
        conversions: "Conversions",
        byChannel: "By channel",
        topCampaigns: "Top campaigns",
        campaignsNeedingReview: "Campaigns needing review",
        spend: "spend",
        funnelLeads: "Leads",
        funnelMqls: "MQLs",
        funnelSqls: "SQLs",
        funnelWon: "Won",
        conversion: "conversion",
        overallConversion: "Overall Conversion",
        avgSalesCycle: "Avg Sales Cycle",
        days: "days",
        bottleneckStage: "Bottleneck Stage",
        bySource: "By Source",
        sourceSummary: "{leads} leads → {won} won ({rate})",
        retention30d: "30-Day Retention",
        retention90d: "90-Day Retention",
        monthlyChurn: "Monthly Churn",
        avgLtv: "Avg LTV",
        ltvCacRatio: "LTV:CAC Ratio",
        retentionTrend: "Retention Trend",
        cohortsAnalyzed: "Cohorts Analyzed",
        bestCohort: "Best Cohort",
        worstCohort: "Worst Cohort",
        retention: "retention",
        trendImproving: "Improving",
        trendDeclining: "Declining",
        trendStable: "Stable",
        cmoSummary: "CMO Summary",
        marketingHealth: "Marketing Health",
        growthEfficiency: "Growth Efficiency",
        topRisks: "Top Risks",
        quickWins: "Quick Wins",
        effortLabel: "Effort:",
        companyName: "Company Name",
        period: "Period",
        campaignCsvLabel: "Campaign CSV (Google Ads / Meta Ads)",
        funnelCsvLabel: "Funnel CSV (HubSpot / Salesforce)",
        cohortCsvLabel: "Cohort CSV (Mixpanel / Amplitude)",
        validationError: "At least one data source is required.",
        analyzing: "Analyzing...",
        runAnalysis: "Run CMO Analysis",
        csvPasteHeading: "Run by pasting CSV",
        pipelineError: "Pipeline error:",
      },
    },
    chro: {
      title: "People & organization",
      description: "Workforce structure, attrition risk, and compensation alignment in one view.",
      sections: {
        headcountOverview: "Headcount Overview",
        attritionAnalysis: "Attrition Analysis",
        compensationAnalysis: "Compensation Analysis",
        hrHealthSummary: "HR Health Summary",
      },
      body: {
        totalHeadcount: "Total Headcount",
        totalFte: "Total FTE",
        newHires30d: "New Hires (30d)",
        avgTenure: "Avg Tenure",
        yrs: "yrs",
        netChange30d: "Net Change (30d):",
        byDepartment: "By Department",
        avg: "avg",
        noAlerts: "No alerts.",
        totalAttritions: "Total Attritions",
        voluntary: "Voluntary",
        annualRate: "Annual Rate",
        attritionCost: "Attrition Cost",
        topDepartureReasons: "Top Departure Reasons",
        highAttritionRiskRoles: "High Attrition Risk Roles",
        riskLabel: "Risk:",
        totalPayroll: "Total Payroll",
        avgSalary: "Avg Salary",
        equityBurn: "Equity Burn",
        benefitsCost: "Benefits Cost",
        belowMarket: "Below Market:",
        aboveMarket: "Above Market:",
        byLevel: "By Level",
        employees: "employees",
        hrScore: "HR Score",
        topHrRisks: "Top HR Risks",
        quickWins: "Quick Wins",
        effort: "effort",
        validationError: "All three CSV inputs (headcount, attrition, compensation) are required.",
        unknownError: "Unknown error",
        csvManualHeading: "Manual analysis via CSV",
        companyName: "Company Name",
        period: "Period",
        headcountCsvLabel: "Headcount CSV",
        attritionCsvLabel: "Attrition CSV",
        compensationCsvLabel: "Compensation CSV",
        analyzing: "Analyzing...",
        runAnalysis: "Run CHRO Analysis",
        loadExampleData: "Load Example Data",
        pipelineError: "Pipeline error:",
      },
    },
    coo: {
      title: "Operational performance",
      description: "Track process bottlenecks, delivery times, and service-level risks.",
      sections: {
        bottlenecks: "Process Bottlenecks (Throughput vs Cycle Time)",
        tocAnalysis: "Theory of Constraints (ToC) Analysis",
        overdueTickets: "Overdue Tickets",
        atRiskTickets: "At-Risk Tickets",
      },
      body: {
        cycleTimeAxis: "Cycle Time (days)",
        throughputAxis: "Throughput (items/day)",
        bottlenecksSeries: "Bottlenecks",
        constraintLabels: {
          resource: "Human Resources",
          policy: "Policy",
          market: "Market",
          material: "Material",
        },
        impactScore: "Impact Score",
        overdueTicketsLine: "{overdue} / {total} open tickets are past their due date",
        trendExplanation:
          "A trend needs ticket lists from multiple periods; no trend is drawn from a single upload.",
        colTicket: "Ticket",
        colTitle: "Title",
        colAssigned: "Assigned",
        colRemainingHours: "Hours Left",
        colUrgency: "Urgency",
        colPriority: "Priority",
        timeExpired: "Time expired",
        near: "due soon",
        watching: "monitoring",
        validationError: "At least one data source (processes or SLA CSV) is required.",
        csvManualHeading: "Manual analysis via CSV",
        companyName: "Company Name",
        period: "Period",
        processesCsvLabel: "Processes CSV",
        slaCsvLabel: "SLA / Tickets CSV",
        analyzing: "Analyzing...",
        runAnalysis: "Run COO Analysis",
        noResults: "No process or SLA results were found for this analysis.",
        errorPrefix: "Error:",
      },
    },
  },
  decisionBrief: {
    title: "Decision Brief",
    empty: "No decision brief yet. Run a CFO analysis or rebuild the semantic model.",
    rebuild: "Rebuild brief",
    rebuildAria: "Rebuild decision brief",
    reportingPeriod: "Reporting period",
    vsPrior: "vs prior period",
    awaitingReview: "Awaiting review",
    cleared: "Cleared",
    approve: "Approve brief",
    approving: "Approving…",
    findings: "Findings",
    confidence: "conf",
    recommendation: "Recommendation",
    whatIf: "What-if options",
    runSimulation: "Run simulation →",
    conflicts: "{count} open agent conflict(s) included in this brief.",
    gateHeld: "Confidence gate held this brief for human review before auto-proceed.",
    domains: {
      finance: "Finance",
      growth: "Growth",
      people: "People",
      risk: "Risk",
      governance: "Governance",
      general: "General",
      ceo: "CEO",
    },
  },
};
