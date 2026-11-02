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
  provenance: {
    real: string;
    realHint: string;
    estimated: string;
    estimatedHint: string;
    benchmark: string;
    benchmarkHint: string;
  };
  ruleFeedback: {
    badgeRule: string;
    badgeRuleHint: string;
    badgeEdit: string;
    badgeEditHint: string;
    bannerTitle: string;
    bannerBody: string;
    rerun: string;
    rerunning: string;
    queued: string;
    partial: string;
    dismiss: string;
  };
  authAtlas: {
    ariaLabel: string;
    caption: string;
    ledger: string;
    invoices: string;
    bank: string;
    cfo: string;
    risk: string;
    ceo: string;
    verifier: string;
    decision: string;
  };
  demo: {
    preparing: string;
    failedRetry: string;
    sandboxTag: string;
    bannerTitle: string;
    bannerBody: string;
    specPnl: string;
    specAnomalies: string;
    specMonteCarlo: string;
    starting: string;
    startSample: string;
  };
  macroStress: {
    title: string;
    subtitle: string;
    sourceTag: string;
    refresh: string;
    usdTry: string;
    eurTry: string;
    policyRate: string;
    inflation: string;
    paramsTitle: string;
    usdShock: string;
    eurShock: string;
    rateDelta: string;
    delayDays: string;
    daysValue: string;
    outputTitle: string;
    stressedRunway: string;
    runwayDelta: string;
    monthsValue: string;
    noRunwayLimit: string;
    cashTurnsNegative: string;
    monthlyIncrease: string;
    perMonth: string;
    recsTitle: string;
    noBaseline: string;
    loadError: string;
    estimateBasis: string;
    assumptionsNote: string;
    risk: {
      CRITICAL: string;
      HIGH: string;
      MODERATE: string;
      LOW: string;
      CASH_NEGATIVE: string;
    };
    recs: {
      fx_contracts_to_try: string;
      fx_hedge: string;
      fixed_rate_loans: string;
      early_payment_discount: string;
    };
  };
  analytics: {
    macro: {
      title: string;
      policyRate: string;
      inflation: string;
      ufe: string;
      repoRate: string;
      loadError: string;
      wacc: string;
    };
    benchmark: {
      title: string;
      percentiles: string;
      strengths: string;
      improvements: string;
      loadError: string;
    };
    loadError: string;
    title: string;
    subtitle: string;
    refresh: string;
    errorTitle: string;
    emptyTitle: string;
    emptyBody: string;
    info: string;
  };
  commandCenter: {
    title: string;
    subtitle: string;
    generateDeck: string;
    conflicts: string;
    turkeyPackHint: string;
    deckNoJob: string;
    deckGenerated: string;
    deckSynthesis: string;
    deckFailed: string;
    relNow: string;
    relMins: string;
    relHours: string;
    relDays: string;
    nodeRunning: string;
    nodeWaiting: string;
    pipelineRunning: string;
    pipelineDone: string;
    domainAnalyses: string;
    ceoSynthesis: string;
    deckReady: string;
    pdfError: string;
    pdfAria: string;
    pdfDownloading: string;
    pdfDownload: string;
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
    modeTabs: {
      aria: string;
      single: string;
      batch: string;
    };
    clientBanner: {
      fileFor: string;
      selectedClient: string;
      change: string;
    };
    dropzone: {
      aria: string;
      analyzing: string;
      hint: string;
      sources: string;
      limits: string;
    };
    error: {
      processFailed: string;
      uploadFailed: string;
      formatsLabel: string;
      maxSizeLabel: string;
      supportedExports: string;
      retryAsCsv: string;
    };
    health: {
      excellent: string;
      good: string;
      fair: string;
      poor: string;
      critical: string;
    };
    issues: {
      errors: string;
      warnings: string;
      infos: string;
      showLess: string;
      showMore: string;
    };
    mapping: {
      heading: string;
      hint: string;
      confirm: string;
      needDateAmount: string;
      nullShare: string;
      fields: {
        none: string;
        date: string;
        amount: string;
        description: string;
        category: string;
        reference: string;
      };
    };
    review: {
      regionAria: string;
      encoding: string;
      delimiter: string;
      differentFile: string;
      uploadAnyway: string;
    };
    uploading: {
      heading: string;
      body: string;
    };
    done: {
      heading: string;
      body: string;
      goTo: string;
    };
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
    hydration: string;
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
        noCfoInputHint: string;
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
        fillWithSample: string;
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
        recentHires: string;
        avgTenure: string;
        yrs: string;
        netChange: string;
        byDepartment: string;
        avg: string;
        noAlerts: string;
        totalAttritions: string;
        voluntary: string;
        earlyRate: string;
        attritionCost: string;
        topDepartureReasons: string;
        totalPayroll: string;
        avgSalary: string;
        equityBurn: string;
        benefitsCost: string;
        belowMarket: string;
        aboveMarket: string;
        byLevel: string;
        employees: string;
        employeeOne: string;
        hrScore: string;
        topHrRisks: string;
        scoreScaleNote: string;
        quickWins: string;
        effort: string;
        effortLevel: { low: string; medium: string; high: string };
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
        tocDefault: string;
      };
    };
    cfo: {
      title: string;
      description: string;
      sections: {
        pnlSummary: string;
        cashFlow: string;
        forecast: string;
        opex: string;
        reports: string;
        alerts: string;
        related: string;
      };
      body: {
        pnlSubtitle: string;
        revenue: string;
        grossProfit: string;
        ebitda: string;
        netProfit: string;
        totalCogs: string;
        margin: string;
        cfoComment: string;
        noExpenseData: string;
        amount: string;
        cashFlowSubtitle: string;
        netChange: string;
        operating: string;
        investing: string;
        financing: string;
        monthlyCashMovement: string;
        chartLegendAria: string;
        inflow: string;
        outflow: string;
        forecastSubtitle: string;
        colScenario: string;
        colNet12: string;
        colRunway: string;
        colAssumption: string;
        months: string;
        stable: string;
        reportsEmpty: string;
        reportsSubtitle: string;
        download: string;
        downloadAria: string;
        showAll: string;
        alertsSubtitle: string;
        loadingAria: string;
        emptyHeading: string;
        emptyBody: string;
        uploadData: string;
        lastAnalysis: string;
        transactionCount: string;
        pnlDetail: string;
        cashFlowLink: string;
        opexSubtitle: string;
        related: {
          forecast: string;
          budget: string;
          anomalies: string;
          tax: string;
          whatIf: string;
          comparison: string;
          ceo: string;
          risk: string;
        };
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
  pnl: {
    title: string;
    subtitle: string;
    kpi: {
      revenue: string;
      totalIncome: string;
      grossProfit: string;
      ebitda: string;
      netIncome: string;
      margin: string;
    };
    waterfall: {
      heading: string;
      flow: string;
      amount: string;
      revenue: string;
      cogs: string;
      netIncome: string;
    };
    opex: {
      heading: string;
      total: string;
      amount: string;
      labels: { [key: string]: string };
    };
    statement: {
      heading: string;
      subtitle: string;
      aria: string;
      colLine: string;
      colAmount: string;
      revenue: string;
      cogs: string;
      grossProfit: string;
      grossMargin: string;
      operatingExpenses: string;
      totalOpex: string;
      ebitda: string;
      ebitdaMargin: string;
      netIncome: string;
      netMargin: string;
      cfoCommentary: string;
    };
    empty: {
      heading: string;
      body: string;
      cta: string;
    };
    benchmark: {
      title: string;
      subtitle: string;
      sector: string;
      refresh: string;
      refreshing: string;
      loading: string;
      median: string;
      vsMedian: string;
      recommendation: string;
      source: string;
      percentile: {
        top25: string;
        p50p75: string;
        p25p50: string;
        bottom25: string;
      };
      sectors: { [key: string]: string };
      metrics: { [key: string]: string };
    };
  };
  cashflow: {
    title: string;
    metrics: {
      operating: string;
      investing: string;
      financing: string;
      netChange: string;
    };
    monthly: {
      heading: string;
      subtitle: string;
      empty: string;
      seriesIn: string;
      seriesOut: string;
    };
    net: {
      heading: string;
      subtitle: string;
      series: string;
    };
    table: {
      aria: string;
      colMonth: string;
      colIn: string;
      colOut: string;
      colNet: string;
      colFlow: string;
      colBalance: string;
      projected: string;
      breakdown: string;
      total: string;
    };
    empty: {
      heading: string;
      body: string;
      cta: string;
    };
  };
  baglan: {
    title: string;
    subtitle: string;
    areas: { [key: string]: string };
    dropzone: {
      aria: string;
      reading: string;
      hint: string;
      formats: string;
    };
    uploadFailed: string;
    linkedPages: string;
    help: {
      title: string;
      body: string;
    };
    records: string;
    goToPage: string;
    columnsRead: string;
    thisFile: string;
    choose: string;
    addAsThisType: string;
    email: {
      title: string;
      fetchFailed: string;
      copyFailed: string;
      refreshFailed: string;
      copyAria: string;
      refreshAddress: string;
      refreshConfirm: string;
      refresh: string;
      cancel: string;
      inboxTitle: string;
      inboxEmpty: string;
      noSubject: string;
      open: string;
      statuses: { [key: string]: string };
    };
  };
  chat: {
    title: string;
    welcomeBody: string;
    suggestions: {
      financial: string;
      cash: string;
      risk: string;
      q: {
        topExpenses: string;
        margins: string;
        ebitda: string;
        cashOutlook: string;
        runway: string;
        baseNetCash: string;
        anomalies: string;
        budgetBreaches: string;
        taxObligations: string;
      };
    };
    followups: {
      detail: string;
      improve: string;
      benchmark: string;
      actions: string;
    };
    noJob: {
      heading: string;
      body: string;
      cta: string;
    };
    copyAria: string;
    thinkingAria: string;
    clearAria: string;
    clear: string;
    sendAria: string;
    inputAria: string;
    placeholder: string;
    typing: string;
    mode: {
      toStream: string;
      toGrounded: string;
      grounded: string;
      stream: string;
      ws: string;
      sse: string;
    };
    simulation: {
      detected: string;
      done: string;
      failed: string;
      headcount: string;
      cascade: string;
      scenario: string;
    };
    errorPrefix: string;
    unknownError: string;
    disclaimer: string;
    footer: string;
  };
  budget: {
    title: string;
    subtitle: string;
    thisPeriod: string;
    summary: {
      budgeted: string;
      actual: string;
      variance: string;
      variancePct: string;
      categoriesOver: string;
    };
    chart: {
      heading: string;
      hint: string;
      tooltip: string;
    };
    table: {
      heading: string;
      colCategory: string;
      colBudget: string;
      colActual: string;
      colVariance: string;
      colStatus: string;
    };
    empty: {
      heading: string;
      body: string;
      cta: string;
    };
    noBudget: {
      heading: string;
      body: string;
    };
    cfoCommentary: string;
  };
  tax: {
    title: string;
    subtitle: string;
    kpi: {
      vatNet: string;
      vatSub: string;
      withholding: string;
      salaryBase: string;
      ssi: string;
      ssiSub: string;
      corporate: string;
      effectiveRate: string;
      total: string;
      paid: string;
      paidSub: string;
    };
    calendar: {
      heading: string;
      subtitle: string;
      empty: string;
      daysLeft: string;
      today: string;
      overdue: string;
    };
    breakdown: {
      heading: string;
      subtitle: string;
      colLine: string;
      colAmount: string;
      rows: {
        outputVat: string;
        inputVat: string;
        netVat: string;
        grossSalary: string;
        incomeTax: string;
        ssiEmployer: string;
        payrollTax: string;
        taxableIncome: string;
        corporateEst: string;
      };
    };
    empty: {
      heading: string;
      body: string;
      cta: string;
    };
    noTax: {
      heading: string;
      body: string;
    };
    advisorCommentary: string;
  };
  trends: {
    title: string;
    subtitle: string;
    badges: {
      improving: string;
      declining: string;
      stable: string;
      insufficient: string;
    };
    kpi: {
      overall: string;
      monthsData: string;
      revenue: string;
      expenses: string;
      expenseUp: string;
      net: string;
    };
    mom: {
      heading: string;
      revenue: string;
      expenses: string;
      net: string;
      empty: string;
    };
    yoy: {
      heading: string;
      empty: string;
    };
    chart: {
      heading: string;
      subtitle: string;
      empty: string;
      revenue: string;
      expense: string;
      net: string;
    };
    table: {
      heading: string;
      colMonth: string;
      colRevenue: string;
      colExpense: string;
      colNet: string;
    };
    empty: {
      heading: string;
      body: string;
      cta: string;
    };
    noTrend: {
      heading: string;
      body: string;
    };
    cfoAnalysis: string;
  };
  comparison: {
    title: string;
    subtitle: string;
    refresh: string;
    errors: {
      jobs: string;
      compare: string;
    };
    selector: {
      heading: string;
      empty: string;
      hint: string;
      comparing: string;
      compare: string;
    };
    metrics: {
      colMetric: string;
      labels: {
        revenue: string;
        gross_profit: string;
        gross_margin: string;
        ebitda: string;
        ebitda_margin: string;
        net_income: string;
        net_margin: string;
        opex: string;
        cash_flow: string;
      };
    };
    emptyResult: {
      heading: string;
      body: string;
    };
    summary: string;
    changesHeading: string;
    chart: {
      heading: string;
      revenue: string;
      margin: string;
    };
    info: string;
  };
  sensitivity: {
    title: string;
    subtitle: string;
    noJob: {
      heading: string;
      body: string;
      cta: string;
    };
    tabs: {
      matrix: string;
      single: string;
    };
    varsLoading: string;
    labels: {
      rowVar: string;
      colVar: string;
      singleVar: string;
    };
    run: string;
    calculating: string;
    error: string;
    needAnalysis: string;
    info: {
      body: string;
      ex1: string;
      ex2: string;
      ex3: string;
    };
    heatmap: {
      heading: string;
      subtitle: string;
      showMargin: string;
      showNet: string;
      legendHigh: string;
      legendBase: string;
      legendLow: string;
      baseNet: string;
      bestCase: string;
      worstCase: string;
      marginTooltip: string;
      netTooltip: string;
    };
    single: {
      heading: string;
      subtitle: string;
      breakeven: string;
      tooltip: string;
    };
  };
  forecast: {
    title: string;
    fan: {
      heading: string;
      tip: string;
      hint: string;
      empty: string;
      band: string;
      pessimistic: string;
      optimistic: string;
      base: string;
    };
    kpi: {
      baseNet: string;
      runway: string;
      runwayStable: string;
      optimisticUpside: string;
      pessimisticDownside: string;
      vsBase: string;
    };
    table: {
      heading: string;
      hint: string;
      colScenario: string;
      colNet: string;
      colRunway: string;
      colAssumption: string;
      monthsShort: string;
      stable: string;
      ariaLabel: string;
    };
    breakdown: {
      heading: string;
      subtitle: string;
      revenue: string;
      expenses: string;
      net: string;
    };
    empty: {
      heading: string;
      body: string;
      cta: string;
    };
  };
  integrations: {
    title: string;
    subtitle: string;
    loading: string;
    neverSynced: string;
    ago: {
      justNow: string;
      mins: string;
      hours: string;
      days: string;
    };
    card: {
      lastSync: string;
      lastCount: string;
      itemsCount: string;
      transactions: string;
      tokenExpired: string;
      confirmRemove: string;
      syncError: string;
      syncWarning: string;
      remove: string;
      removeConfirm: string;
    };
    connect: {
      heading: string;
      subtitle: string;
      cta: string;
    };
    file: {
      heading: string;
      loading: string;
      empty: string;
      dropHint: string;
      logoHint: string;
      processing: string;
      submit: string;
      success: string;
      successStarted: string;
    };
    connected: string;
    addHeading: string;
    allConnected: string;
    logs: {
      heading: string;
      historyHeading: string;
      toCfo: string;
    };
    erp: {
      heading: string;
      logoTiger: string;
      mikro: string;
    };
    csv: {
      heading: string;
      bothConnected: string;
    };
    providers: {
      parasut: { label: string; description: string };
      logo_tiger: { label: string; description: string };
      mikro: { label: string; description: string };
      netsis: { label: string; description: string };
    };
  };
  intelligence: {
    title: string;
    subtitle: string;
    refresh: string;
    error: string;
    goldenPath: string;
    status: {
      healthy: string;
      warning: string;
      critical: string;
    };
    kpi: {
      noHistory: string;
      trendHeading: string;
      cashRunway: string;
      margin: string;
      threshold: string;
    };
    empty: {
      heading: string;
      body: string;
      bodyLong: string;
      cta: string;
      ctaCommand: string;
    };
    semantic: {
      ready: string;
      link: string;
    };
    prereq: { pre: string; link: string; post: string };
    weekly: {
      critical: string;
      warning: string;
      healthy: string;
    };
    recommendations: string;
    loading: string;
  };
  anomalies: {
    title: string;
    subtitle: string;
    issuesFound: string;
    dismissedCount: string;
    filters: {
      all: string;
      critical: string;
      high: string;
      medium: string;
      low: string;
      ariaBy: string;
      allTypes: string;
      ariaType: string;
      clear: string;
      shown: string;
      noMatch: string;
    };
    types: {
      duplicate_payment: string;
      unusual_amount: string;
      unusual_vendor: string;
      vendor_concentration: string;
      negative_cashflow_streak: string;
      expense_spike: string;
      missing_revenue: string;
      round_number: string;
      late_payment: string;
      fx_concentration: string;
    };
    acknowledged: string;
    showAck: string;
    hideAck: string;
    dismissed: string;
    rescan: string;
    scanning: string;
    ariaRescan: string;
    restore: string;
    dismiss: string;
    ariaRestore: string;
    ariaDismiss: string;
    confidence: string;
    rca: {
      open: string;
      close: string;
      heading: string;
      analyzing: string;
      error: string;
    };
    empty: { heading: string; body: string; cta: string };
    clean: { heading: string; body: string };
  };
  reports: {
    title: string;
    subtitle: string;
    close: string;
    closePreview: string;
    download: string;
    downloadJson: string;
    downloaded: string;
    preparing: string;
    preview: string;
    previewLabel: string;
    jsonPreview: string;
    loading: string;
    error: string;
    loadError: string;
    noJob: string;
    jsonOnly: string;
    generated: string;
    generatedPlural: string;
    empty: { heading: string; body: string; cta: string };
    types: {
      full: { label: string; description: string };
      pnl: { label: string; description: string };
      cashflow: { label: string; description: string };
      forecast: { label: string; description: string };
    };
  };
  templates: {
    title: string;
    subtitle: string;
    upload: string;
    downloadAll: string;
    templatesCount: string;
    columns: string;
    downloadFile: string;
    howto: {
      heading: string;
      step1: string;
      step2: string;
      step3: string;
      step4: string;
    };
  };
  notifications: {
    title: string;
    subtitle: string;
    levels: {
      critical: string;
      error: string;
      warning: string;
      info: string;
    };
    ago: {
      justNow: string;
      mins: string;
      hours: string;
      days: string;
    };
    priority: string;
    markRead: string;
    markAllRead: string;
    delete: string;
    prefs: {
      heading: string;
      channels: string;
      channelDashboard: string;
      channelEmail: string;
      channelSlack: string;
      minSeverity: string;
      sevInfo: string;
      sevWarning: string;
      sevCritical: string;
      slackUrl: string;
      slackTest: string;
      slackSending: string;
      slackSuccess: string;
      slackError: string;
      emailRecipients: string;
      save: string;
      saving: string;
      saved: string;
    };
    tabs: {
      all: string;
      unread: string;
      settings: string;
    };
    filters: {
      all: string;
    };
    empty: string;
    emptyUnread: string;
  };
  smmm: {
    title: string;
    subtitle: string;
    panelFallback: string;
    refresh: string;
    close: string;
    cancel: string;
    loadError: string;
    deleteConfirm: string;
    deleteError: string;
    addClientButton: string;
    odaNo: string;
    notRegistered: { body: string; cta: string };
    register: {
      title: string;
      save: string;
      saving: string;
      saveError: string;
      fields: {
        unvan: string;
        firmaAdi: string;
        vergiNo: string;
        odaNo: string;
        il: string;
        telefon: string;
      };
    };
    addClient: {
      title: string;
      submit: string;
      adding: string;
      firmaAdiRequired: string;
      addError: string;
      fields: {
        firmaAdi: string;
        firmaAdiPlaceholder: string;
        vergiNo: string;
        il: string;
        ilPlaceholder: string;
        sektor: string;
        buyukluk: string;
        notlar: string;
      };
    };
    stage: {
      veri_yok: string;
      basarisiz: string;
      onay_bekliyor: string;
      analiz_edildi: string;
      muhurlendi: string;
    };
    attention: {
      pendingEntries: string;
      reviewNeeded: string;
      noFiles: string;
      nothingPending: string;
    };
    actions: {
      analyze: string;
      analyzeAria: string;
      delete: string;
      deleteAria: string;
    };
    summary: {
      total: string;
      analyzed: string;
      awaitingYou: string;
      sealed: string;
      pendingEntries: string;
    };
    table: {
      title: string;
      count: string;
      cols: {
        firma: string;
        sektor: string;
        il: string;
        saglik: string;
        durum: string;
        sonAnaliz: string;
        islem: string;
      };
    };
    empty: { heading: string; body: string; cta: string };
  };
  smmmOnay: {
    title: string;
    subtitle: string;
    refresh: string;
    cancel: string;
    processing: string;
    loadError: string;
    pendingBadge: string;
    status: {
      bekliyor: string;
      onaylandi: string;
      duzeltildi: string;
      reddedildi: string;
    };
    filters: {
      all: string;
      bekliyor: string;
      onaylandi: string;
      duzeltildi: string;
      reddedildi: string;
    };
    bulk: {
      selectAll: string;
      confirm: string;
      approve: string;
      error: string;
    };
    duzelt: {
      title: string;
      codeLabel: string;
      codePlaceholder: string;
      nameLabel: string;
      namePlaceholder: string;
      reasonLabel: string;
      save: string;
      saving: string;
      codeRequired: string;
      nameRequired: string;
      saveError: string;
    };
    red: {
      title: string;
      reasonLabel: string;
      reasonPlaceholder: string;
      submit: string;
      reasonRequired: string;
      rejectError: string;
    };
    card: {
      noDescription: string;
      selectAria: string;
      showOriginal: string;
      hideDetails: string;
    };
    actions: {
      approve: string;
      correct: string;
      reject: string;
    };
    empty: {
      allApproved: string;
      allApprovedBody: string;
      noRecords: string;
      noRecordsBody: string;
    };
  };
  audit: {
    title: string;
    subtitle: string;
    loadSample: string;
    run: string;
    analyzing: string;
    unknownError: string;
    validationError: string;
    pipelineError: string;
    form: {
      company: string;
      period: string;
      findingsCsv: string;
      controlsCsv: string;
      coverageCsv: string;
      csvPlaceholder: string;
    };
    heatmap: {
      title: string;
      cellTooltip: string;
      cellValue: string;
      types: { design: string; operating: string };
    };
    trend: {
      title: string;
      repeat: string;
      newFindings: string;
    };
    gantt: {
      title: string;
      footer: string;
      riskLevels: { high: string; medium: string; low: string };
      tasks: {
        it: string;
        finance: string;
        hr: string;
        vendor: string;
        security: string;
      };
    };
    modal: {
      severity: string;
      status: string;
      category: string;
      owner: string;
      dueDate: string;
      daysLate: string;
      remediationStatus: string;
      close: string;
    };
    summary: {
      heading: string;
      overallScore: string;
      maturity: string;
    };
    topFindings: string;
    sort: {
      severity: string;
      dueDate: string;
      overdue: string;
    };
  };
  risk: {
    title: string;
    loading: string;
    run: string;
    noDataBody: string;
    tabs: {
      overview: string;
      matrix: string;
      cascade: string;
      categories: string;
    };
    empty: {
      heading: string;
      bodyWithData: string;
      bodyNoData: string;
      cta: string;
    };
    kpi: {
      posture: string;
      noMeasuredKri: string;
      red: string;
      totalCount: string;
      amber: string;
      greenCount: string;
      cascade: string;
      domainsAffected: string;
      sources: string;
    };
    lists: {
      red: string;
      amber: string;
      cascadeReady: string;
    };
    matrix: {
      legend: string;
      axis: string;
      likelihood: {
        rare: string;
        unlikely: string;
        possible: string;
        likely: string;
        almostCertain: string;
      };
      impact: {
        insignificant: string;
        minor: string;
        moderate: string;
        major: string;
        critical: string;
      };
    };
    categories: {
      financial: string;
      people: string;
      technology: string;
      market: string;
      operational: string;
      compliance: string;
    };
    cascadeEmpty: string;
    cascade: {
      title: string;
      subtitle: string;
      disclaimer: string;
      triggers: {
        heading: string;
        cash_crisis: { label: string; desc: string };
        revenue_drop: { label: string; desc: string };
        key_person_loss: { label: string; desc: string };
        cyber_incident: { label: string; desc: string };
        custom: { label: string; desc: string };
      };
      severity: {
        heading: string;
        low: string;
        medium: string;
        high: string;
        critical: string;
      };
      context: {
        heading: string;
        hint: string;
        burnRate: string;
        revenue: string;
        runway: string;
        headcount: string;
      };
      customDesc: {
        label: string;
        placeholder: string;
      };
      run: string;
      running: string;
      errorPrefix: string;
      errorFallback: string;
      empty: {
        heading: string;
        body: string;
      };
      loading: {
        heading: string;
        body: string;
      };
      result: {
        idLabel: string;
        riskLevel: string;
        recovery: string;
        priorities: string;
        sequence: string;
        domainHeading: string;
        impactScoreAria: string;
        timeToImpact: string;
      };
      card: {
        show: string;
        hide: string;
        secondary: string;
        actions: string;
      };
    };
  };
  simulation: {
    title: string;
    subtitle: string;
    goldenPath: string;
    tip: {
      label: string;
      body: string;
    };
    tabs: {
      cascade: { label: string; desc: string };
      counterfactual: { label: string; desc: string };
      nl: { label: string; desc: string };
    };
  };
  iliskiliTaraf: {
    title: string;
    subtitle: string;
    loading: string;
    relationships: {
      ortak: string;
      yonetici: string;
      aile: string;
      istirak: string;
      anaOrtaklik: string;
      kilitPersonel: string;
      diger: string;
    };
    matchedOn: {
      taxId: string;
      exactName: string;
      nameInText: string;
    };
    errors: {
      load: string;
      add: string;
      remove: string;
    };
    suggestions: {
      heading: string;
      body: string;
      row: string;
      addAria: string;
      add: string;
    };
    check: {
      heading: string;
      body: string;
      placeholder: string;
      try: string;
      matched: string;
      basis: string;
      basisNote: string;
      noMatch: string;
      registryEmpty: string;
    };
    register: {
      heading: string;
      count: string;
      namePlaceholder: string;
      relationshipAria: string;
      add: string;
      empty: string;
      matchKey: string;
      taxId: string;
      removeAria: string;
      remove: string;
      footnote: string;
    };
  };
  trVertical: {
    title: string;
    subtitle: string;
    jobLabel: string;
    noJobs: string;
    companyPlaceholder: string;
    start: string;
    running: string;
    unknownError: string;
    reconciliation: string;
    ungrounded: string;
    stages: {
      ingest: string;
      cfo: string;
      accounting: string;
      boardDeck: string;
      done: string;
    };
    approval: {
      autoOk: string;
      autoOkBody: string;
      waiting: string;
      queueLink: string;
    };
    pnl: {
      summary: string;
      revenue: string;
      grossProfit: string;
      ebitda: string;
      netProfit: string;
      transactions: string;
      marginLine: string;
    };
    deck: {
      ready: string;
      size: string;
      download: string;
      downloadError: string;
    };
    accounting: {
      title: string;
      transactions: string;
      journalEntries: string;
      pendingApproval: string;
      balance: string;
      balanced: string;
      unbalanced: string;
    };
  };
  baslangic: {
    title: string;
    subtitle: string;
    loadErrorTitle: string;
    loadErrorFallback: string;
    retry: string;
    progress: {
      complete: string;
      count: string;
      aria: string;
    };
    steps: {
      company: { title: string; body: string };
      data: {
        title: string;
        body: string;
        cta: string;
        parasutConnected: string;
        uploaded: string;
      };
      analysis: { title: string; body: string; done: string };
      auto: {
        title: string;
        body: string;
        cta: string;
        emailOn: string;
        parasutAuto: string;
      };
    };
    doneBanner: { body: string; cta: string };
    optionalBadge: string;
    status: { done: string; todo: string };
    form: {
      nameLabel: string;
      namePlaceholder: string;
      save: string;
      createError: string;
    };
    analysis: {
      startingSoon: string;
      connectFirst: string;
      approvalTitle: string;
      confidenceLow: string;
      confidenceWith: string;
      viewResults: string;
      approveAndFinish: string;
      confirmTitle: string;
      confirmBody: string;
      cancel: string;
      approve: string;
      approveError: string;
      failedTitle: string;
      noReason: string;
      reconnect: string;
      processing: string;
    };
  };
  kurumsallasma: {
    title: string;
    subtitle: string;
    recompute: string;
    loadError: string;
    recomputeError: string;
    gradeLabel: string;
    trend: string;
    measurements: string;
    dimensions: string;
    weightLine: string;
    recommendations: string;
  };
  pilot: {
    title: string;
    subtitle: string;
    refresh: string;
    loadError: string;
    genericError: string;
    noData: string;
    npsOutOf: string;
    stats: {
      totalUsers: string;
      maxUsers: string;
      freeSlots: string;
      pendingInvites: string;
      usedInvites: string;
    };
    feedback: {
      summary: string;
      npsScore: string;
      promoters: string;
      passives: string;
      detractors: string;
      analysisQuality: string;
      accuracy: string;
      usefulness: string;
      topBenefits: string;
      topGaps: string;
    };
    generate: {
      heading: string;
      emailPlaceholder: string;
      notePlaceholder: string;
      submit: string;
    };
    invites: {
      heading: string;
      used: string;
      copyLink: string;
      revoke: string;
    };
    recent: {
      heading: string;
      npsBadge: string;
    };
    empty: {
      heading: string;
      body: string;
    };
  };
  settingsAlerts: {
    title: string;
    subtitle: string;
    enable: string;
    slackLabel: string;
    slackPlaceholder: string;
    emailLabel: string;
    emailPlaceholder: string;
    save: string;
    saving: string;
    saved: string;
    savedLocal: string;
    saveFailed: string;
  };
  settingsWorkspace: {
    title: string;
    subtitle: string;
    loading: string;
    createWorkspace: string;
    planBadge: string;
    memberCount: string;
    roles: {
      owner: string;
      admin: string;
      cfo: string;
      analyst: string;
      viewer: string;
    };
    errors: {
      noWorkspace: string;
      loadFailed: string;
      generic: string;
      inviteFailed: string;
    };
    locale: {
      title: string;
      subtitle: string;
      localeLabel: string;
      currencyLabel: string;
      countryLabel: string;
      trPackTitle: string;
      trPackBody: string;
      save: string;
      saved: string;
      saveFailed: string;
    };
    localeOptions: {
      "en-US": string;
      "en-GB": string;
      "tr-TR": string;
      "de-DE": string;
    };
    countries: {
      US: string;
      GB: string;
      TR: string;
      DE: string;
      AE: string;
      SG: string;
    };
    semantic: {
      title: string;
      subtitle: string;
      rebuild: string;
      rebuilt: string;
      rebuildFailed: string;
    };
    alerts: {
      loading: string;
      title: string;
      slack: {
        title: string;
        body: string;
        howto: string;
        webhookLabel: string;
        webhookPlaceholder: string;
        channelLabel: string;
        channelPlaceholder: string;
        test: string;
        testSent: string;
        testFailed: string;
      };
      email: {
        label: string;
        placeholder: string;
        hint: string;
      };
      severity: {
        label: string;
        info: string;
        warning: string;
        critical: string;
        hint: string;
      };
      digest: {
        title: string;
        body: string;
      };
      save: string;
      saved: string;
      saveFailed: string;
    };
    members: {
      title: string;
      empty: string;
      removeAria: string;
    };
    invite: {
      title: string;
      placeholder: string;
      button: string;
      hint: string;
    };
    pendingInvites: {
      title: string;
      expiresAt: string;
      copyAria: string;
      cancelAria: string;
    };
  };
  tetikler: {
    title: string;
    subtitle: string;
    refresh: string;
    loading: string;
    newRule: string;
    editRule: string;
    formName: string;
    formNamePlaceholder: string;
    formEvents: string;
    eventKinds: {
      jobCompleted: { label: string; hint: string };
      txArrived: { label: string; hint: string };
      anomalyDetected: { label: string; hint: string };
      schedule: { label: string; hint: string };
    };
    formCondition: string;
    formConditionPlaceholder: string;
    simpleEditor: string;
    jsonEditor: string;
    formAction: string;
    formCooldown: string;
    formParams: string;
    formParamsPlaceholder: string;
    formEnabled: string;
    submitCreate: string;
    submitSaving: string;
    submitUpdate: string;
    cancel: string;
    dryRunTitle: string;
    dryRunSubtitle: string;
    dryRunCondition: string;
    dryRunConditionPlaceholder: string;
    dryRunValues: string;
    dryRunButton: string;
    dryRunBusy: string;
    dryRunYes: string;
    dryRunNo: string;
    dryRunUnknownMetrics: string;
    dryRunLoadAria: string;
    rulesHeading: string;
    rulesEmpty: string;
    colName: string;
    colEvents: string;
    colAction: string;
    colCooldown: string;
    colEnabled: string;
    colLog: string;
    cooldownUnit: string;
    toggleEnable: string;
    toggleDisable: string;
    editAria: string;
    deleteAria: string;
    logAria: string;
    logFiltered: string;
    logClearFilter: string;
    logHeading: string;
    logFilteredHeading: string;
    logEmpty: string;
    colTime: string;
    colRule: string;
    colEvent: string;
    colStatus: string;
    colDetail: string;
    statusFired: string;
    statusCooldown: string;
    statusConditionFalse: string;
    statusDuplicate: string;
    statusError: string;
    catalogHint: string;
    errNameRequired: string;
    errEventsRequired: string;
    errConditionJson: string;
    errParamsJson: string;
    errValuesJson: string;
    errGeneric: string;
    confirmDelete: string;
    updated: string;
    created: string;
    deleted: string;
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
  provenance: {
    real: "Real",
    realHint: "Measured from a connected source or parsed file",
    estimated: "Estimated",
    estimatedHint: "Extrapolated from history — not a measurement",
    benchmark: "Benchmark",
    benchmarkHint: "Sector assumption / fixed reference — not company data",
  },
  ruleFeedback: {
    badgeRule: "Your rule",
    badgeRuleHint: "A rule you saved decided this category.",
    badgeEdit: "Edited",
    badgeEditHint: "A person changed this category by hand.",
    bannerTitle: "Your rule changes {n} analyses",
    bannerBody: "Their dashboards were computed with the old categories. Rerunning processes their files again with your rules.",
    rerun: "Rerun analyses",
    rerunning: "Starting reruns…",
    queued: "{n} analyses queued.",
    partial: "{ok} of {n} analyses started; sealed or in-review analyses were skipped.",
    dismiss: "Dismiss",
  },
  authAtlas: {
    ariaLabel: "Decision map: company data flows through the CFO, Risk and CEO agents, is independently verified, then becomes a decision.",
    caption: "From data to decision — every figure traceable to its source.",
    ledger: "Ledger",
    invoices: "e-Invoice",
    bank: "Bank",
    cfo: "CFO",
    risk: "Risk",
    ceo: "CEO",
    verifier: "Verification",
    decision: "Decision",
  },
  demo: {
    preparing: "Preparing demo…",
    failedRetry: "Could not start — try again",
    sandboxTag: "Sandbox · Logo Tiger 2024",
    bannerTitle: "Explore the full C-suite analysis loop without uploading data",
    bannerBody: "Start anomaly review, cash-flow stress testing and the board summary on 12 months of realistic SME accounting data in one click.",
    specPnl: "12-month P&L",
    specAnomalies: "Anomaly review",
    specMonteCarlo: "Monte Carlo runway",
    starting: "Starting analysis…",
    startSample: "Start sample company analysis",
  },
  macroStress: {
    title: "TCMB macro indicators & FX/rate shock simulator",
    subtitle: "Deterministic effect of exchange-rate and interest shocks on runway and borrowing cost",
    sourceTag: "TCMB EVDS",
    refresh: "Refresh",
    usdTry: "USD / TRY",
    eurTry: "EUR / TRY",
    policyRate: "Policy rate",
    inflation: "Annual CPI",
    paramsTitle: "Shock scenario",
    usdShock: "USD rate increase (%)",
    eurShock: "EUR rate increase (%)",
    rateDelta: "Interest change (basis points)",
    delayDays: "Collection delay",
    daysValue: "+{n} days",
    outputTitle: "Simulation output",
    stressedRunway: "Runway under stress",
    runwayDelta: "Runway change",
    monthsValue: "{n} mo",
    noRunwayLimit: "No limit",
    cashTurnsNegative: "Monthly cash flow turns negative under this shock",
    monthlyIncrease: "Extra monthly cash out (FX + interest + delay):",
    perMonth: "/ month",
    recsTitle: "Suggested actions",
    noBaseline: "Run a CFO analysis first — the simulator only stresses your own figures, never sample numbers.",
    loadError: "Could not load the simulation.",
    estimateBasis: "Rule-based model on your last CFO analysis",
    assumptionsNote: "Assumptions: {fx}% of opex in FX, debt ≈ {debt} months of opex, based on {months} months of data.",
    risk: {
      CRITICAL: "Critical cash risk",
      HIGH: "High risk",
      MODERATE: "Moderate risk",
      LOW: "Low risk",
      CASH_NEGATIVE: "Cash flow turns negative",
    },
    recs: {
      fx_contracts_to_try: "Negotiate FX-priced cloud/SaaS contracts into annual TRY commitments.",
      fx_hedge: "Consider a forward or futures hedge for your open FX position.",
      fixed_rate_loans: "Move floating-rate loans to fixed, or review early repayment options.",
      early_payment_discount: "Offer large customers an early-payment discount (2–3%) to shorten collection.",
    },
  },
  analytics: {
    macro: {
      title: "TCMB Macroeconomic Indicators",
      policyRate: "Policy Rate",
      inflation: "Inflation",
      ufe: "PPI",
      repoRate: "Repo Rate",
      loadError: "TCMB data could not be loaded",
      wacc: "Real Cost of Capital",
    },
    benchmark: {
      title: "{company} — Sector Benchmark",
      percentiles: "P25 / company / P75",
      strengths: "Strengths",
      improvements: "Areas for Improvement",
      loadError: "Benchmark data could not be loaded",
    },
    loadError: "Data could not be loaded",
    title: "Analytics & Benchmark",
    subtitle: "TCMB macro indicators and sector comparison",
    refresh: "Refresh",
    errorTitle: "Error",
    emptyTitle: "Analysis Pending",
    emptyBody: "The benchmark analysis will appear once financial data has been uploaded.",
    info:
      "TCMB macro data updates daily. The benchmark comparison measures your financial indicators against the Turkish sector average. P25/P50/P75 = 25/50/75 percentiles.",
  },
  commandCenter: {
    title: "Executive Command Center",
    subtitle: "Multi-role management OS — depth follows your data.",
    generateDeck: "Generate board deck",
    conflicts: "Open conflicts",
    turkeyPackHint: "Turkey pack enabled",
    deckNoJob: "No active CFO job - run upload/analysis first.",
    deckGenerated: "Board deck generated - view it on the CEO page.",
    deckSynthesis: "CEO synthesis triggered.",
    deckFailed: "Could not create board deck",
    relNow: "just now",
    relMins: "{n}m ago",
    relHours: "{n}h ago",
    relDays: "{n}d ago",
    nodeRunning: "running",
    nodeWaiting: "waiting",
    pipelineRunning: "{n} running",
    pipelineDone: "{done} / {total} complete",
    domainAnalyses: "Domain Analyses",
    ceoSynthesis: "CEO Synthesis",
    deckReady: "Board deck ready",
    pdfError: "PDF could not be downloaded. Run an analysis first.",
    pdfAria: "Download Board Deck PDF",
    pdfDownloading: "Downloading",
    pdfDownload: "Download Board Deck",
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
    modeTabs: {
      aria: "Upload mode",
      single: "Single upload",
      batch: "Batch upload",
    },
    clientBanner: {
      fileFor: "This file will be uploaded for {client}.",
      selectedClient: "the selected client",
      change: "Change",
    },
    dropzone: {
      aria: "Click or drop a CSV file",
      analyzing: "Analyzing…",
      hint: "Drag a CSV file here or click",
      sources: "Logo Tiger · Parasut · Akbank · Garanti · GIB e-Invoice XML · Generic CSV/Excel",
      limits: "Max 10 MB · .csv, .xlsx, .xls, .pdf, .xml",
    },
    error: {
      processFailed: "The file could not be processed",
      uploadFailed: "Upload failed",
      formatsLabel: "Supported formats:",
      maxSizeLabel: "Maximum size:",
      supportedExports:
        "Logo Tiger, Parasut, Akbank, Garanti, Ziraat and Is Bankasi exports are supported",
      retryAsCsv: "If the problem persists, save the file as CSV and try again",
    },
    health: {
      excellent: "Excellent",
      good: "Good",
      fair: "Fair",
      poor: "Weak",
      critical: "Critical",
    },
    issues: {
      errors: "errors",
      warnings: "warnings",
      infos: "info",
      showLess: "Show less",
      showMore: "show more",
    },
    mapping: {
      heading: "Column mapping",
      hint: "Match columns to system fields",
      confirm: "Confirm mapping & upload",
      needDateAmount: "Match the date and amount columns to continue.",
      nullShare: "{pct}% empty · ",
      fields: {
        none: "— no mapping —",
        date: "Date (required)",
        amount: "Amount (required)",
        description: "Description",
        category: "Category",
        reference: "Reference no",
      },
    },
    review: {
      regionAria: "Data quality report",
      encoding: "Encoding",
      delimiter: "Delimiter",
      differentFile: "Choose a different file",
      uploadAnyway: "Upload anyway",
    },
    uploading: {
      heading: "Uploading…",
      body: "AI agents are preparing",
    },
    done: {
      heading: "Upload complete!",
      body: "The AI agents started the analysis. Redirecting to the dashboard…",
      goTo: "Go now",
    },
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
    hydration: "Loading the last analysis…",
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
        noCfoInputHint:
          "Run the CFO analysis first — the CEO pipeline needs financial or tech data.",
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
        fillWithSample: "Fill with sample data",
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
        recentHires: "Hired (last 12 months)",
        avgTenure: "Avg Tenure",
        yrs: "yrs",
        netChange: "Net change (hires − departures):",
        byDepartment: "By Department",
        avg: "avg",
        noAlerts: "No alerts.",
        totalAttritions: "Total Attritions",
        voluntary: "Voluntary",
        earlyRate: "Early Departures (<6 mo)",
        attritionCost: "Attrition Cost",
        topDepartureReasons: "Top Departure Reasons",
        totalPayroll: "Total Payroll",
        avgSalary: "Avg Salary",
        equityBurn: "Equity Burn",
        benefitsCost: "Benefits Cost",
        belowMarket: "Below Market:",
        aboveMarket: "Above Market:",
        byLevel: "By Level",
        employees: "employees",
        employeeOne: "employee",
        hrScore: "HR Score",
        topHrRisks: "Top HR Risks",
        scoreScaleNote:
          "Components are scored against their own criteria; the overall score is their weighted roll-up.",
        quickWins: "Quick Wins",
        effort: "effort",
        effortLevel: { low: "low", medium: "medium", high: "high" },
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
        tocDefault: "Identify the constraint and increase capacity",
      },
    },
    cfo: {
      title: "CFO overview",
      description: "Financial performance, cash position, and priority items.",
      sections: {
        pnlSummary: "P&L summary",
        cashFlow: "Cash flow",
        forecast: "12-month forecast",
        opex: "Expense breakdown",
        reports: "Reports",
        alerts: "Critical alerts",
        related: "Related analyses",
      },
      body: {
        pnlSubtitle: "Revenue, cost, and profit analysis",
        revenue: "Revenue",
        grossProfit: "Gross profit",
        ebitda: "EBITDA",
        netProfit: "Net profit",
        totalCogs: "Total COGS",
        margin: "{margin} margin",
        cfoComment: "CFO comment",
        noExpenseData: "No expense data",
        amount: "Amount",
        cashFlowSubtitle: "Monthly cash in/out analysis",
        netChange: "Net change",
        operating: "Operating",
        investing: "Investing",
        financing: "Financing",
        monthlyCashMovement: "Monthly cash movement",
        chartLegendAria: "Chart legend",
        inflow: "Inflow",
        outflow: "Outflow",
        forecastSubtitle: "Scenario-based revenue projection",
        colScenario: "Scenario",
        colNet12: "12-month net",
        colRunway: "Runway",
        colAssumption: "Assumption",
        months: "{months} mo",
        stable: "Stable",
        reportsEmpty: "No reports yet. Reports appear here once the analysis finishes.",
        reportsSubtitle: "Downloadable Excel / PDF reports",
        download: "Download",
        downloadAria: "Download {title}",
        showAll: "All",
        alertsSubtitle: "Items that need priority action",
        loadingAria: "Loading CFO data",
        emptyHeading: "Data needed for a CFO analysis",
        emptyBody:
          "Upload a bank statement, invoice CSV, or Excel file — AI CFO prepares your analysis in seconds.",
        uploadData: "Upload data",
        lastAnalysis: "Last analysis {date}",
        transactionCount: "{count} transactions",
        pnlDetail: "P&L detail",
        cashFlowLink: "Cash flow",
        opexSubtitle: "Operating expenses by category",
        related: {
          forecast: "Forecast",
          budget: "Budget",
          anomalies: "Anomalies",
          tax: "Tax",
          whatIf: "What-If",
          comparison: "Comparison",
          ceo: "CEO summary",
          risk: "Risk",
        },
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
  pnl: {
    title: "P&L statement",
    subtitle: "Profit & loss breakdown with operating expense detail",
    kpi: {
      revenue: "Revenue",
      totalIncome: "Total income",
      grossProfit: "Gross profit",
      ebitda: "EBITDA",
      netIncome: "Net income",
      margin: "{margin} margin",
    },
    waterfall: {
      heading: "P&L waterfall",
      flow: "Revenue → COGS → OpEx → Net income",
      amount: "Amount",
      revenue: "Revenue",
      cogs: "COGS",
      netIncome: "Net income",
    },
    opex: {
      heading: "Operating expenses breakdown",
      total: "Total: {amount} · {count} categories",
      amount: "Amount",
      labels: {
        salary: "Salaries & wages",
        rent: "Rent",
        utilities: "Utilities",
        marketing: "Marketing",
        technology: "Technology",
        other_expense: "Other expense",
      },
    },
    statement: {
      heading: "Profit & loss statement",
      subtitle: "Full income statement breakdown",
      aria: "P&L statement",
      colLine: "Line item",
      colAmount: "Amount",
      revenue: "Revenue",
      cogs: "Cost of goods sold (COGS)",
      grossProfit: "Gross profit",
      grossMargin: "Gross margin",
      operatingExpenses: "Operating expenses",
      totalOpex: "Total OpEx",
      ebitda: "EBITDA",
      ebitdaMargin: "EBITDA margin",
      netIncome: "Net income",
      netMargin: "Net margin",
      cfoCommentary: "CFO commentary",
    },
    empty: {
      heading: "No P&L data",
      body: "Upload a financial document and run an analysis to see the P&L statement.",
      cta: "Upload document",
    },
    benchmark: {
      title: "Sector comparison",
      subtitle: "Compare against sector averages from TCMB/BDDK statistics",
      sector: "Sector:",
      refresh: "Refresh",
      refreshing: "Refreshing…",
      loading: "Loading benchmark data…",
      median: "Median",
      vsMedian: "vs median",
      recommendation: "→ Recommendation:",
      source: "Source: TCMB/BDDK Sector Statistics 2023-2024 · {sector}",
      percentile: {
        top25: "Top 25%",
        p50p75: "50–75%",
        p25p50: "25–50%",
        bottom25: "Bottom 25%",
      },
      sectors: {
        default: "Overall average",
        retail: "Retail",
        manufacturing: "Manufacturing",
        technology: "Technology / Software",
        construction: "Construction / Real estate",
        services: "Services",
        food_beverage: "Food & beverage",
        logistics: "Logistics",
      },
      metrics: {
        gross_margin: "Gross margin",
        net_margin: "Net margin",
        ebitda_margin: "EBITDA margin",
        opex_to_revenue: "OpEx / revenue",
      },
    },
  },
  cashflow: {
    title: "Cash flow statement",
    metrics: {
      operating: "Operating",
      investing: "Investing",
      financing: "Financing",
      netChange: "Net change",
    },
    monthly: {
      heading: "Monthly cash flow",
      subtitle: "Cash in vs. out per month",
      empty: "No monthly data available",
      seriesIn: "Cash in",
      seriesOut: "Cash out",
    },
    net: {
      heading: "Monthly net cash flow",
      subtitle: "Positive = surplus · Negative = deficit",
      series: "Net",
    },
    table: {
      aria: "Monthly cash flow",
      colMonth: "Month",
      colIn: "Cash in",
      colOut: "Cash out",
      colNet: "Net",
      colFlow: "Flow",
      colBalance: "Running balance",
      projected: "proj",
      breakdown: "Monthly breakdown",
      total: "Total",
    },
    empty: {
      heading: "No cash flow data",
      body: "Upload a financial document and run an analysis to see cash flow details.",
      cta: "Upload document",
    },
  },
  baglan: {
    title: "Connect my data",
    subtitle:
      "Drop the files you exported from the program you already use (accounting, banking, payroll, ads). The system reads them from their columns; you do not need to rename anything.",
    areas: {
      cfo: "Finance",
      cto: "Technology",
      chro: "Human Resources",
      cmo: "Marketing",
      coo: "Operations",
      risk: "Risk",
      audit: "Internal Audit",
      compliance: "Compliance",
    },
    dropzone: {
      aria: "Drop a file or choose one",
      reading: "Reading files…",
      hint: "Drop files here, or click to choose",
      formats: "Excel (.xlsx), CSV or PDF · you can drop several at once · up to 10 files",
    },
    uploadFailed: "The files could not be sent.",
    linkedPages: "Data added to:",
    help: {
      title: "What can I connect?",
      body: "Start with a bank statement or an accounting file; the other files are linked to it.",
    },
    records: "{count} records",
    goToPage: "Go to page →",
    columnsRead: "Which columns were read",
    thisFile: "This file:",
    choose: "Choose…",
    addAsThisType: "Add as this type",
    email: {
      title: "Send automatically by email",
      fetchFailed: "Could not fetch the address.",
      copyFailed: "Could not copy; select the address and copy it yourself.",
      refreshFailed: "The address could not be refreshed.",
      copyAria: "Copy address",
      refreshAddress: "Refresh address",
      refreshConfirm: "Mail sent to the old address will no longer be received. Are you sure?",
      refresh: "Refresh",
      cancel: "Cancel",
      inboxTitle: "Incoming emails",
      inboxEmpty: "No email has arrived yet.",
      noSubject: "(no subject)",
      open: "open",
      statuses: {
        eklendi: "added",
        onceden_alindi: "already received",
        secim_gerekli: "type must be chosen",
        taninmadi: "not recognised",
        reddedildi: "rejected",
        finansal_dosya_gerekli: "statement needed first",
        ek_yok: "no attachment",
      },
    },
  },
  chat: {
    title: "CFO Assistant",
    welcomeBody: "Ask anything about your financial data — reports, risks, forecasts.",
    suggestions: {
      financial: "Financial position",
      cash: "Cash & forecast",
      risk: "Risk & alerts",
      q: {
        topExpenses: "What were the biggest expenses this month?",
        margins: "How are margins trending?",
        ebitda: "Show EBITDA and drivers",
        cashOutlook: "What does cash look like next month?",
        runway: "What is our runway at this burn?",
        baseNetCash: "What is net cash in the base scenario?",
        anomalies: "Are there any anomalies this month?",
        budgetBreaches: "Where did we breach budget?",
        taxObligations: "What are our upcoming tax obligations?",
      },
    },
    followups: {
      detail: "Detail",
      improve: "How to improve",
      benchmark: "Compare to sector",
      actions: "Recommended actions",
    },
    noJob: {
      heading: "Start an analysis first",
      body: "Upload a financial document — the assistant becomes available once the analysis finishes.",
      cta: "Upload document",
    },
    copyAria: "Copy message",
    thinkingAria: "Assistant is typing",
    clearAria: "Clear conversation",
    clear: "Clear",
    sendAria: "Send",
    inputAria: "Chat message",
    placeholder: "Ask a financial question or “what if X”…",
    typing: "Generating answer…",
    mode: {
      toStream: "Switch to stream",
      toGrounded: "Switch to grounded",
      grounded: "Grounded (RAG + KPI)",
      stream: "Stream",
      ws: "WS Streaming",
      sse: "SSE Streaming",
    },
    simulation: {
      detected: "Simulation question detected — the NL Simulation Engine will be used",
      done: "Simulation complete.",
      failed: "Simulation could not be run.",
      headcount: "Headcount simulation",
      cascade: "Cascade risk",
      scenario: "Scenario analysis",
    },
    errorPrefix: "Something went wrong: ",
    unknownError: "Unknown error",
    disclaimer: "AI answers should be verified with your accountant.",
    footer: "Enter to send · Shift+Enter for a new line · AI answers should be verified with your accountant.",
  },
  budget: {
    title: "Budget comparison",
    subtitle: "Planned vs. actual spend · {period}",
    thisPeriod: "This period",
    summary: {
      budgeted: "Budget",
      actual: "Actual",
      variance: "Variance",
      variancePct: "Variance (%)",
      categoriesOver: "{count} categories over",
    },
    chart: {
      heading: "Variance by category (%)",
      hint: "Positive = over budget · Negative = saving",
      tooltip: "Variance",
    },
    table: {
      heading: "Budget comparison table",
      colCategory: "Category",
      colBudget: "Budget",
      colActual: "Actual",
      colVariance: "Variance",
      colStatus: "Status",
    },
    empty: {
      heading: "No budget data",
      body: "Add budget data when starting the analysis — send budget_input with the analysis request to get a comparison.",
      cta: "Upload document",
    },
    noBudget: {
      heading: "No budget comparison",
      body: "No budget data was provided for this analysis. Add the budget_input parameter when starting it.",
    },
    cfoCommentary: "CFO commentary",
  },
  tax: {
    title: "Tax analysis",
    subtitle: "{month} · VAT, withholding and corporate tax estimate",
    kpi: {
      vatNet: "VAT (net)",
      vatSub: "Output: {output} / Input: {input}",
      withholding: "Withholding",
      salaryBase: "Salary base: {amount}",
      ssi: "SSI employer",
      ssiSub: "Including total payroll load",
      corporate: "Corporate tax",
      effectiveRate: "Effective rate: {rate}%",
      total: "Total tax burden",
      paid: "Paid per the books",
      paidSub: "{n} payments · from the ledger, not an estimate",
    },
    calendar: {
      heading: "Payment calendar",
      subtitle: "Upcoming tax obligations and due dates",
      empty: "No upcoming tax payments.",
      daysLeft: "{count} days left",
      today: "Today!",
      overdue: "Overdue",
    },
    breakdown: {
      heading: "Tax breakdown",
      subtitle: "Estimated tax obligations for {month}",
      colLine: "Line item",
      colAmount: "Amount",
      rows: {
        outputVat: "Output VAT (from sales)",
        inputVat: "Input VAT (from purchases, deductible)",
        netVat: "Net VAT payable",
        grossSalary: "Gross salary payments",
        incomeTax: "Income tax withholding (%15)",
        ssiEmployer: "SSI employer share (%22.5)",
        payrollTax: "Total payroll tax",
        taxableIncome: "Taxable income",
        corporateEst: "Corporate tax estimate (%25)",
      },
    },
    empty: {
      heading: "No tax data",
      body: "Upload a financial document and run an analysis — tax calculations are made automatically.",
      cta: "Upload document",
    },
    noTax: {
      heading: "No tax calculation found",
      body: "No tax data is available for this analysis. Re-run the analysis.",
    },
    advisorCommentary: "Tax advisor commentary",
  },
  trends: {
    title: "Period analysis & trends",
    subtitle: "{range} · {months} months of data",
    badges: {
      improving: "Improving",
      declining: "Declining",
      stable: "Stable",
      insufficient: "Insufficient data",
    },
    kpi: {
      overall: "Overall direction",
      monthsData: "{count} months of data",
      revenue: "Revenue trend",
      expenses: "Expense trend",
      expenseUp: "↑ increase = bad",
      net: "Net trend",
    },
    mom: {
      heading: "Month over month (MoM)",
      revenue: "Revenue",
      expenses: "Expenses",
      net: "Net cash flow",
      empty: "At least 2 months of data are needed to compare.",
    },
    yoy: {
      heading: "Year over year (YoY)",
      empty: "12+ months of data are needed for a YoY comparison.",
    },
    chart: {
      heading: "Monthly trend chart",
      subtitle: "Revenue, expense and net cash flow trend",
      empty: "The trend chart needs at least 2 months of data.",
      revenue: "Revenue",
      expense: "Expense",
      net: "Net",
    },
    table: {
      heading: "Monthly summary table",
      colMonth: "Month",
      colRevenue: "Revenue",
      colExpense: "Expense",
      colNet: "Net",
    },
    empty: {
      heading: "No trend data",
      body: "Upload a document containing at least 2 months of data.",
      cta: "Upload document",
    },
    noTrend: {
      heading: "No period analysis found",
      body: "Not enough period data for this analysis. At least 2 months are needed.",
    },
    cfoAnalysis: "CFO analysis",
  },
  comparison: {
    title: "Period comparison",
    subtitle: "Q1 vs Q2, 2023 vs 2024 — compare financial metrics side by side",
    refresh: "Refresh",
    errors: {
      jobs: "Jobs could not be loaded",
      compare: "Comparison failed",
    },
    selector: {
      heading: "Period selection",
      empty: "No analyses to compare. Upload at least 2 periods.",
      hint: "You can select 2–3 periods. {selected}/{total} selected.",
      comparing: "Comparing…",
      compare: "Compare",
    },
    metrics: {
      colMetric: "Metric",
      labels: {
        revenue: "Revenue",
        gross_profit: "Gross profit",
        gross_margin: "Gross margin",
        ebitda: "EBITDA",
        ebitda_margin: "EBITDA margin",
        net_income: "Net income",
        net_margin: "Net margin",
        opex: "OpEx",
        cash_flow: "Cash flow",
      },
    },
    emptyResult: {
      heading: "Ready to compare",
      body: "Pick 2–3 periods from the left panel to compare.",
    },
    summary: "Summary",
    changesHeading: "Changes between periods",
    chart: {
      heading: "Revenue vs margin trend",
      revenue: "Revenue (million {currency})",
      margin: "Net margin (%)",
    },
    info: "You can select up to 3 periods. The comparison shows the differences, percentage changes and trends between each period's financial indicators.",
  },
  sensitivity: {
    title: "What-if analysis",
    subtitle: "What would your net income be if the variables sat at different levels?",
    noJob: {
      heading: "Analysis required",
      body: "Run a CFO analysis first to use sensitivity analysis.",
      cta: "Upload data",
    },
    tabs: {
      matrix: "2D matrix",
      single: "Single variable",
    },
    varsLoading: "Loading variables…",
    labels: {
      rowVar: "Row variable (Y axis)",
      colVar: "Column variable (X axis)",
      singleVar: "Variable to analyse",
    },
    run: "Run analysis",
    calculating: "Calculating…",
    error: "Error: a CFO analysis must be run first.",
    needAnalysis: "Run a CFO analysis before using sensitivity analysis.",
    info: {
      body: "Pick your variables above and click {run}.",
      ex1: "What if headcount drops 20%?",
      ex2: "What if prices rise 10%?",
      ex3: "What if operating expenses change?",
    },
    heatmap: {
      heading: "Sensitivity matrix",
      subtitle: "{row} (rows) × {col} (columns)",
      showMargin: "Show margin %",
      showNet: "Show net income",
      legendHigh: "Highest",
      legendBase: "Base",
      legendLow: "Lowest",
      baseNet: "Base net income:",
      bestCase: "Best case",
      worstCase: "Worst case",
      marginTooltip: "Margin: {val}%",
      netTooltip: "Net income: {val}",
    },
    single: {
      heading: "{label} analysis",
      subtitle: "How net income is affected as this variable changes",
      breakeven: "Break-even: net income hits zero at a {threshold}% change",
      tooltip: "Net income",
    },
  },
  forecast: {
    title: "12-month forecast",
    fan: {
      heading: "Monte Carlo projection fan",
      tip: "The shaded band represents the full range between optimistic and pessimistic scenarios",
      hint: "Shaded band = scenario spread · solid line = base case",
      empty: "No projection data available",
      band: "Confidence band",
      pessimistic: "Pessimistic",
      optimistic: "Optimistic",
      base: "Base",
    },
    kpi: {
      baseNet: "Base case 12-month net",
      runway: "{count} months runway",
      runwayStable: "Stable runway",
      optimisticUpside: "Optimistic upside",
      pessimisticDownside: "Pessimistic downside",
      vsBase: "vs base case",
    },
    table: {
      heading: "Scenario comparison",
      hint: "Click a row to view its monthly breakdown below",
      colScenario: "Scenario",
      colNet: "12-month net",
      colRunway: "Runway",
      colAssumption: "Assumption",
      monthsShort: "{count} mo",
      stable: "Stable",
      ariaLabel: "Forecast scenarios",
    },
    breakdown: {
      heading: "{label} — monthly breakdown",
      subtitle: "Revenue, expenses and net cash flow per month",
      revenue: "Revenue",
      expenses: "Expenses",
      net: "Net",
    },
    empty: {
      heading: "No forecast data",
      body: "Upload a financial document and run an analysis to generate 12-month forecasts.",
      cta: "Upload document",
    },
  },
  integrations: {
    title: "Integrations",
    subtitle: "Connect your accounting software, bank and e-Invoice",
    loading: "Loading…",
    neverSynced: "Never synced",
    ago: {
      justNow: "Just now",
      mins: "{count} min ago",
      hours: "{count} h ago",
      days: "{count} d ago",
    },
    card: {
      lastSync: "Last sync",
      lastCount: "Last transactions",
      itemsCount: "{count} items",
      transactions: "{count} transactions",
      tokenExpired: "OAuth token expired — reconnect",
      confirmRemove: "Delete?",
      syncError: "Sync error",
      syncWarning: "Sync warning",
      remove: "Remove",
      removeConfirm: "Remove this integration?",
    },
    connect: {
      heading: "Connect with a file",
      subtitle: "Drop the Excel, CSV or PDF files from your software — the system figures out what they are.",
      cta: "Connect my data",
    },
    file: {
      heading: "CSV sync",
      loading: "Loading…",
      empty: "No sync performed yet.",
      dropHint: "Drag a CSV file or select",
      logoHint: "Logo Tiger: voucher list, account movements",
      processing: "Processing…",
      submit: "Upload and start CFO analysis",
      success: "{count} transactions synced",
      successStarted: "{count} transactions synced — CFO analysis started",
    },
    connected: "Connected integrations",
    addHeading: "Add integration",
    allConnected: "All supported integrations are connected.",
    logs: {
      heading: "Sync log",
      historyHeading: "Sync history",
      toCfo: "→ CFO",
    },
    erp: {
      heading: "ERP integrations",
      logoTiger: "Logo Tiger CSV Sync",
      mikro: "Mikro ERP CSV Sync",
    },
    csv: {
      heading: "CSV file sync",
      bothConnected: "You have connected both file-based integrations.",
    },
    providers: {
      parasut: { label: "Paraşüt", description: "Cloud accounting — invoices and expenses" },
      logo_tiger: { label: "Logo Tiger", description: "ERP — vouchers and account movements via CSV" },
      mikro: { label: "Mikro ERP", description: "ERP — vouchers and account movements via CSV" },
      netsis: { label: "Netsis", description: "ERP — inventory and finance modules" },
    },
  },
  intelligence: {
    title: "Proactive KRI dashboard",
    subtitle: "Key Risk Indicators — hourly KRI scans and semantic metrics",
    refresh: "Refresh",
    error: "KRI data could not be loaded",
    goldenPath: "Live sync + semantic brief ready",
    status: {
      healthy: "Healthy",
      warning: "Warning",
      critical: "Critical",
    },
    kpi: {
      noHistory: "No KRI history",
      trendHeading: "KRI trend (last 30 days)",
      cashRunway: "Cash runway (months)",
      margin: "Margin (%)",
      threshold: "Threshold: {value}{unit}",
    },
    empty: {
      heading: "KRI analysis pending",
      body: "Run an analysis to see key risk indicators.",
      bodyLong: "Indicators will appear once financial data is uploaded or live sync completes.",
      cta: "Go to dashboard",
      ctaCommand: "Command Center →",
    },
    semantic: {
      ready: "Semantic metrics are ready. A CFO analysis must complete for the full KRI trend chart —",
      link: "Start CFO analysis",
    },
    prereq: { pre: "To see the KRI dashboard, a CFO analysis must be ", link: "completed", post: " first." },
    weekly: {
      critical: "{count} critical alerts this week",
      warning: "{count} warnings this week",
      healthy: "All indicators are healthy",
    },
    recommendations: "Recommendations",
    loading: "Loading…",
  },
  anomalies: {
    title: "Anomaly Detection",
    subtitle: "AI-powered financial anomaly scanner",
    issuesFound: "{count} issues found",
    dismissedCount: "({count} dismissed)",
    filters: {
      all: "Total",
      critical: "Critical",
      high: "High",
      medium: "Medium",
      low: "Low",
      ariaBy: "Filter by {label}",
      allTypes: "All types",
      ariaType: "Filter by anomaly type",
      clear: "Clear filters",
      shown: "{count} shown",
      noMatch: "No anomalies match the current filters.",
    },
    types: {
      duplicate_payment: "Duplicate Payment",
      unusual_amount: "Unusual Amount",
      unusual_vendor: "Unusual Vendor",
      vendor_concentration: "Vendor Concentration",
      negative_cashflow_streak: "Negative Cash Flow Streak",
      expense_spike: "Expense Spike",
      missing_revenue: "Missing Revenue",
      round_number: "Round Number Pattern",
      late_payment: "Late Payment",
      fx_concentration: "FX Concentration",
    },
    acknowledged: "Acknowledged",
    showAck: "Show acknowledged",
    hideAck: "Hide acknowledged",
    dismissed: "Dismissed",
    rescan: "Re-scan",
    scanning: "Scanning…",
    ariaRescan: "Re-scan for anomalies",
    restore: "Restore",
    dismiss: "Dismiss",
    ariaRestore: "Restore anomaly",
    ariaDismiss: "Acknowledge anomaly",
    confidence: "Confidence: {pct}%",
    rca: {
      open: "Explain with AI",
      close: "Close",
      heading: "🔍 Root Cause Analysis",
      analyzing: "Analyzing…",
      error: "Analysis could not be started.",
    },
    empty: {
      heading: "No anomaly data",
      body: "Complete an analysis first, then scan for anomalies.",
      cta: "Upload document",
    },
    clean: {
      heading: "All clear",
      body: "No anomalies detected in your financial data.",
    },
  },
  reports: {
    title: "Reports",
    subtitle: "Download or preview generated financial reports",
    close: "Close",
    closePreview: "Close preview",
    download: "Download",
    downloadJson: "Download JSON",
    downloaded: "Downloaded",
    preparing: "Preparing…",
    preview: "Preview",
    previewLabel: "Preview {type}",
    jsonPreview: "JSON preview · {date}",
    loading: "Loading…",
    error: "Failed to load",
    loadError: "Failed to load reports. The analysis may still be running.",
    noJob: "No analysis selected. Open a dashboard with a job ID to see its reports.",
    jsonOnly: "JSON only",
    generated: "{count} report generated",
    generatedPlural: "{count} reports generated",
    empty: {
      heading: "No reports yet",
      body: "Run an analysis from the Upload page to generate P&L, cash flow, and forecast reports.",
      cta: "Upload document",
    },
    types: {
      full: { label: "Full Financial Report", description: "Complete P&L, cash flow, forecast, and KPIs" },
      pnl: { label: "P&L Statement", description: "Profit & loss with OPEX breakdown" },
      cashflow: { label: "Cash Flow Statement", description: "Operating, investing, and financing activities" },
      forecast: { label: "12-Month Forecast", description: "Scenario analysis with Monte Carlo simulation" },
    },
  },
  templates: {
    title: "CSV templates",
    subtitle: "Download sample CSV files for each agent and adapt them to your own data",
    upload: "Upload data",
    downloadAll: "Download all ({count} files)",
    templatesCount: "{count} templates",
    columns: "Columns",
    downloadFile: "Download {file}",
    howto: {
      heading: "How to use?",
      step1: "Download the domain template you need (e.g. CHRO → Employee list)",
      step2: "Fill the template with your own data — do not change the column names",
      step3: "Upload the bank statement and domain files on the Data upload page",
      step4: "AI agents will combine all data to produce a comprehensive analysis",
    },
  },
  notifications: {
    title: "Notifications",
    subtitle: "System and analysis alerts",
    levels: {
      critical: "Critical",
      error: "Error",
      warning: "Warning",
      info: "Info",
    },
    ago: {
      justNow: "just now",
      mins: "{count} minutes ago",
      hours: "{count} hours ago",
      days: "{count} days ago",
    },
    priority: "Priority: {score}",
    markRead: "Mark as read",
    markAllRead: "Mark all as read",
    delete: "Delete",
    prefs: {
      heading: "Notification preferences",
      channels: "Channels",
      channelDashboard: "Dashboard",
      channelEmail: "Email",
      channelSlack: "Slack",
      minSeverity: "Minimum severity",
      sevInfo: "Info (all)",
      sevWarning: "Warning and above",
      sevCritical: "Critical only",
      slackUrl: "Slack Webhook URL",
      slackTest: "Test",
      slackSending: "Sending…",
      slackSuccess: "✓ Test message sent",
      slackError: "Slack test failed",
      emailRecipients: "Email recipients (comma-separated)",
      save: "Save",
      saving: "Saving…",
      saved: "✓ Saved",
    },
    tabs: {
      all: "All",
      unread: "Unread",
      settings: "Settings",
    },
    filters: {
      all: "All",
    },
    empty: "No notifications found",
    emptyUnread: "No unread notifications",
  },
  smmm: {
    title: "SMMM Portal",
    subtitle: "{name} — multi-client management",
    panelFallback: "Accountant panel",
    refresh: "Refresh",
    close: "Close",
    cancel: "Cancel",
    loadError: "Could not load data. Please try again.",
    deleteConfirm: "Remove this client from the list? Past records are kept.",
    deleteError: "Could not remove the client",
    addClientButton: "Add client",
    odaNo: "Chamber reg. no: {no}",
    notRegistered: {
      body: "This module is for accountants. Register as SMMM to manage all your client companies from a single panel.",
      cta: "Register as SMMM",
    },
    register: {
      title: "SMMM registration",
      save: "Save",
      saving: "Saving…",
      saveError: "Registration failed",
      fields: {
        unvan: "Title (SMMM / YMM)",
        firmaAdi: "Company name",
        vergiNo: "Tax no.",
        odaNo: "Chamber registration no.",
        il: "Province",
        telefon: "Phone",
      },
    },
    addClient: {
      title: "Add new client",
      submit: "Add client",
      adding: "Adding…",
      firmaAdiRequired: "Company name is required",
      addError: "Could not add the client",
      fields: {
        firmaAdi: "Company name *",
        firmaAdiPlaceholder: "e.g. ABC Yazılım A.Ş.",
        vergiNo: "Tax no.",
        il: "Province",
        ilPlaceholder: "Istanbul",
        sektor: "Sector",
        buyukluk: "Size",
        notlar: "Notes",
      },
    },
    stage: {
      veri_yok: "No data",
      basarisiz: "Failed",
      onay_bekliyor: "Awaiting approval",
      analiz_edildi: "Analyzed",
      muhurlendi: "Sealed",
    },
    attention: {
      pendingEntries: "{count} entries awaiting your approval",
      reviewNeeded: "Needs review",
      noFiles: "No files uploaded yet",
      nothingPending: "Nothing pending",
    },
    actions: {
      analyze: "Start analysis",
      analyzeAria: "Start analysis for {name}",
      delete: "Delete client",
      deleteAria: "Delete client {name}",
    },
    summary: {
      total: "Total clients",
      analyzed: "Analyzed",
      awaitingYou: "Waiting on you",
      sealed: "Sealed",
      pendingEntries: "{count} entries",
    },
    table: {
      title: "Client list",
      count: "{count} clients",
      cols: {
        firma: "Company",
        sektor: "Sector",
        il: "Province",
        saglik: "Health",
        durum: "Status",
        sonAnaliz: "Last analysis",
        islem: "Actions",
      },
    },
    empty: {
      heading: "No clients yet",
      body: "Add a client to start an analysis.",
      cta: "Add your first client",
    },
  },
  smmmOnay: {
    title: "SMMM Approval Queue",
    subtitle: "The agent prepares, the accountant approves in one click",
    refresh: "Refresh",
    cancel: "Cancel",
    processing: "Processing…",
    loadError: "Could not load the data",
    pendingBadge: "{count} pending",
    status: {
      bekliyor: "Pending",
      onaylandi: "Approved",
      duzeltildi: "Corrected",
      reddedildi: "Rejected",
    },
    filters: {
      all: "All",
      bekliyor: "Pending",
      onaylandi: "Approved",
      duzeltildi: "Corrected",
      reddedildi: "Rejected",
    },
    bulk: {
      selectAll: "Select all ({count})",
      confirm: "Approve all {count} entries?",
      approve: "Bulk approve {count} entries",
      error: "Bulk approval failed",
    },
    duzelt: {
      title: "Account code correction",
      codeLabel: "Account code *",
      codePlaceholder: "e.g. 320",
      nameLabel: "Account name *",
      namePlaceholder: "e.g. Vendors",
      reasonLabel: "Reason (optional)",
      save: "Save correction",
      saving: "Saving…",
      codeRequired: "Account code is required",
      nameRequired: "Account name is required",
      saveError: "Could not save the correction",
    },
    red: {
      title: "Reject entry",
      reasonLabel: "Rejection reason *",
      reasonPlaceholder: "Why was it rejected?",
      submit: "Reject",
      reasonRequired: "A rejection reason is required",
      rejectError: "Could not reject the entry",
    },
    card: {
      noDescription: "No transaction description",
      selectAria: "Select {name}",
      showOriginal: "View original entry",
      hideDetails: "Hide details",
    },
    actions: {
      approve: "Approve",
      correct: "Correct and approve",
      reject: "Reject",
    },
    empty: {
      allApproved: "All entries approved — the queue is empty!",
      allApprovedBody: "Low-confidence transactions land here when a new analysis runs.",
      noRecords: "No entries with this filter",
      noRecordsBody: "Choose a different filter or start an analysis.",
    },
  },
  audit: {
    title: "Internal Audit Dashboard",
    subtitle: "Findings tracking, control effectiveness, and audit coverage analysis",
    loadSample: "Load sample data",
    run: "Run audit",
    analyzing: "Analyzing…",
    unknownError: "Unknown error",
    validationError: "At least one data source (findings, controls or coverage CSV) is required.",
    pipelineError: "Pipeline error:",
    form: {
      company: "Company name",
      period: "Audit period",
      findingsCsv: "Findings CSV",
      controlsCsv: "Controls CSV",
      coverageCsv: "Coverage CSV",
      csvPlaceholder: "Paste CSV data...",
    },
    heatmap: {
      title: "Control Effectiveness Heatmap (IIA Maturity)",
      cellTooltip: "{category} - {type}: {pct}%",
      cellValue: "{pct}%",
      types: { design: "Design", operating: "Operating" },
    },
    trend: {
      title: "Repeat Findings Trend",
      repeat: "Repeat",
      newFindings: "New",
    },
    gantt: {
      title: "90-Day Audit Plan",
      footer: "Total: {days} days | Parallel: {count} audits | Coverage: {coverage}%",
      riskLevels: { high: "High", medium: "Medium", low: "Low" },
      tasks: {
        it: "IT Infrastructure",
        finance: "Financial Controls",
        hr: "HR Operations",
        vendor: "Vendor Management",
        security: "Information Security",
      },
    },
    modal: {
      severity: "Severity",
      status: "Status",
      category: "Category",
      owner: "Owner",
      dueDate: "Due date",
      daysLate: "{count} days overdue",
      remediationStatus: "Remediation status",
      close: "Close",
    },
    summary: {
      heading: "Audit Summary",
      overallScore: "Overall score",
      maturity: "Maturity",
    },
    topFindings: "Top Findings ({count})",
    sort: {
      severity: "Severity",
      dueDate: "Due date",
      overdue: "Days overdue",
    },
  },
  risk: {
    title: "Risk Dashboard",
    loading: "Loading...",
    run: "Run analysis",
    noDataBody:
      "No measured risk indicator. Cash runway or profit margin was not found in the financial report and no KRI file was uploaded. Estimated indicators are not produced.",
    tabs: {
      overview: "Overview",
      matrix: "Risk Matrix",
      cascade: "Cascades ({count})",
      categories: "Categories",
    },
    empty: {
      heading: "Risk analysis has not run yet",
      bodyWithData: "Company data is available. Click the button to start the analysis.",
      bodyNoData: "First upload financial data, then run the risk analysis from here.",
      cta: "Start risk analysis",
    },
    kpi: {
      posture: "Risk posture",
      noMeasuredKri: "no measured KRI",
      red: "Red KRIs",
      totalCount: "{count} total",
      amber: "Amber KRIs",
      greenCount: "{count} green",
      cascade: "Cascade Risk",
      domainsAffected: "{count} domains affected",
      sources: "KRI sources: {sources}",
    },
    lists: {
      red: "🔴 Red KRIs",
      amber: "🟡 Amber KRIs",
      cascadeReady: "⚡ Can Trigger Cascade",
    },
    matrix: {
      legend: "Risk matrix: likelihood × impact. Each dot represents one KRI.",
      axis: "Likelihood ↑ / Impact →",
      likelihood: {
        rare: "Rare",
        unlikely: "Unlikely",
        possible: "Possible",
        likely: "Likely",
        almostCertain: "Almost Certain",
      },
      impact: {
        insignificant: "Insignificant",
        minor: "Minor",
        moderate: "Moderate",
        major: "Major",
        critical: "Critical",
      },
    },
    categories: {
      financial: "Financial",
      people: "Human Resources",
      technology: "Technology",
      market: "Market",
      operational: "Operational",
      compliance: "Compliance",
    },
    cascadeEmpty: "No KRI that could trigger a cascade risk was found.",
    cascade: {
      title: "Cascade Risk Simulator",
      subtitle:
        "\"What happens if…?\" — How does a single triggering event affect every department?",
      disclaimer:
        "This screen is a scenario tool: cascade effects are calculated with generally accepted industry rules. They are not ratios measured from your historical data; the results are not a forecast but a \"where should I look if such an event happens\" checklist.",
      triggers: {
        heading: "Trigger Scenario",
        cash_crisis: {
          label: "Cash Crisis",
          desc: "What happens if cash reserves drop to a critical level?",
        },
        revenue_drop: {
          label: "Revenue Drop",
          desc: "How is every department affected if revenue falls sharply?",
        },
        key_person_loss: {
          label: "Key Person Loss",
          desc: "If the CTO, CPO or a critical executive leaves?",
        },
        cyber_incident: {
          label: "Cyber Attack",
          desc: "If a data breach or ransomware attack happens?",
        },
        custom: {
          label: "Custom Scenario",
          desc: "Define your own scenario",
        },
      },
      severity: {
        heading: "Severity Level",
        low: "Low",
        medium: "Medium",
        high: "High",
        critical: "Critical",
      },
      context: {
        heading: "Financial Context (Optional)",
        hint: "Enter these values to make the simulation more realistic.",
        burnRate: "Monthly burn rate ({symbol})",
        revenue: "Monthly revenue ({symbol})",
        runway: "Cash runway (months)",
        headcount: "Headcount",
      },
      customDesc: {
        label: "Scenario description",
        placeholder: "e.g. Our main supplier went bankrupt and we have no stock for 3 months…",
      },
      run: "Run Simulation",
      running: "Simulating…",
      errorPrefix: "Error:",
      errorFallback: "Simulation failed",
      empty: {
        heading: "Simulation ready",
        body:
          "Pick a scenario and a severity level from the left panel, then press the \"Run Simulation\" button.",
      },
      loading: {
        heading: "Calculating impact…",
        body: "Analyzing cascade effects across all domains",
      },
      result: {
        idLabel: "Simulation #{id}",
        riskLevel: "{level} risk",
        recovery: "~{weeks} weeks to recovery",
        priorities: "Urgent Priorities",
        sequence: "Cascade Impact Flow",
        domainHeading: "Domain Impact Analysis",
        impactScoreAria: "Impact score: {score}/100",
        timeToImpact: "Impact within {weeks} weeks",
      },
      card: {
        show: "Details & Actions",
        hide: "Hide",
        secondary: "Secondary Effects",
        actions: "Recommended Actions",
      },
    },
  },
  simulation: {
    title: "Simulation Center",
    subtitle: "Simulate economic and management scenarios, analyze their C-Suite impact.",
    goldenPath: "Live sync + semantic brief ready — simulations use canonical baselines.",
    tip: {
      label: "Tip:",
      body:
        "When company data is loaded, simulations use your real financial metrics. For now you can work with sample values.",
    },
    tabs: {
      cascade: {
        label: "Cascade Risk",
        desc: "Simulate how a risk event spreads across all domains",
      },
      counterfactual: {
        label: "Action Analysis",
        desc: "See the CFO + CHRO + CTO + CMO impact of a decision",
      },
      nl: {
        label: "Natural Language",
        desc: "Ask a question like \"What happens if I hire 5 engineers?\"",
      },
    },
  },
  iliskiliTaraf: {
    title: "Related Party Register",
    subtitle:
      "The persons and entities your company is connected to. An entry against a registered party goes to the owner's approval and to the declaration when it enters the journal — TMS 24 makes disclosure of these transactions mandatory.",
    loading: "Loading…",
    relationships: {
      ortak: "Partner",
      yonetici: "Executive",
      aile: "Family member",
      istirak: "Subsidiary stake",
      anaOrtaklik: "Parent undertaking",
      kilitPersonel: "Key personnel",
      diger: "Other",
    },
    matchedOn: {
      taxId: "tax ID number",
      exactName: "exact name",
      nameInText: "name appearing in the description",
    },
    errors: {
      load: "Could not load the register",
      add: "Could not be added",
      remove: "Could not be removed",
    },
    suggestions: {
      heading: "Counterparties you pay regularly",
      body:
        "Names that appear more than once in your past transactions and are not in the register. Which of these are you connected to?",
      row: "{count} transactions · {amount}",
      addAria: "Relationship type for {name}",
      add: "Add to register",
    },
    check: {
      heading: "Try a counterparty",
      body:
        "Paste a bank statement line exactly as it is; see whether it trips the register and on what basis.",
      placeholder: "January office rent - ÖZTÜRK HOLDING A.Ş.",
      try: "Try",
      matched: "matched — {relationship}.",
      basis: "Basis: {basis}",
      basisNote:
        "When this transaction enters the journal it awaits the owner's approval and the declaration.",
      noMatch: "No match in the register — this transaction proceeds through the normal flow.",
      registryEmpty: "The register is still empty.",
    },
    register: {
      heading: "Register",
      count: "{count} records",
      namePlaceholder: "Name or legal title",
      relationshipAria: "Relationship type",
      add: "Add",
      empty:
        "The register is empty. An empty register flags nothing — start from the list above or type a name.",
      matchKey: "match key:",
      taxId: "VKN/TCKN",
      removeAria: "Remove {name} from the register",
      remove: "Remove",
      footnote:
        "Removed entries are not deleted but deactivated: when a sealed period asks why something reached approval, the answer has to stand.",
    },
  },
  trVertical: {
    title: "TR Accounting Autopilot (L3)",
    subtitle:
      "Processes the uploaded file in a single pass — CFO analysis → THP journal entries → board presentation — and stops at a single approval gate. No automatic approval.",
    jobLabel: "Completed analysis job",
    noJobs: "No completed jobs",
    companyPlaceholder: "Company name (optional)",
    start: "Start autopilot",
    running: "Running…",
    unknownError: "Unknown error",
    reconciliation: "Reconciliation: {action}",
    ungrounded: "ungrounded",
    stages: {
      ingest: "Data Intake",
      cfo: "CFO Analysis",
      accounting: "TR Accounting (THP)",
      boardDeck: "Board Presentation",
      done: "Completed",
    },
    approval: {
      autoOk: "No approval needed — you can continue automatically",
      autoOkBody:
        "The CFO analysis, reconciliation, and journal entries are consistent. Still, a human approves the final decision.",
      waiting: "Waiting for human approval",
      queueLink: "Go to the SMMM approval queue",
    },
    pnl: {
      summary: "CFO Summary",
      revenue: "Revenue",
      grossProfit: "Gross Profit",
      ebitda: "EBITDA",
      netProfit: "Net Profit / Loss",
      transactions: "{count} transactions",
      marginLine: "Net margin: {margin}% · min. confidence: {confidence}%",
    },
    deck: {
      ready: "Board presentation generated",
      size: "({size} KB)",
      download: "Download",
      downloadError: "PDF could not be downloaded.",
    },
    accounting: {
      title: "TR Accounting (THP)",
      transactions: "Transactions",
      journalEntries: "Journal Entries",
      pendingApproval: "Pending Approval",
      balance: "Balance",
      balanced: "Balanced",
      unbalanced: "Unbalanced",
    },
  },
  baslangic: {
    title: "Getting started",
    subtitle:
      "The steps left before you can use the system. Each step is read from your own data; as you complete one, this page updates itself.",
    loadErrorTitle: "Could not read status",
    loadErrorFallback: "Could not read the status.",
    retry: "Try again",
    progress: {
      complete: "Setup complete",
      count: "{done} of 3 steps done",
      aria: "Setup progress",
    },
    steps: {
      company: {
        title: "Define your company",
        body: "Analyses and reports are issued in this company's name.",
      },
      data: {
        title: "Connect your data",
        body: "Just drop the file you exported from your accounting program or your bank — the system works out what it is.",
        cta: "Connect my data",
        parasutConnected: "Paraşüt connected",
        uploaded: "{count} files uploaded",
      },
      analysis: {
        title: "Your first analysis",
        body: "The analysis starts on its own once your data arrives.",
        done: "{count} analyses completed",
      },
      auto: {
        title: "Let the data arrive on its own",
        body: "Instead of uploading files by hand every time, send them to your dedicated email address or put your Paraşüt connection on autopilot.",
        cta: "Set it to automatic",
        emailOn: "Email address enabled",
        parasutAuto: "Paraşüt automatic",
      },
    },
    doneBanner: {
      body: "Setup complete. Your company's status lives in the Command Center.",
      cta: "Command Center",
    },
    optionalBadge: "optional",
    status: {
      done: "done",
      todo: "to do",
    },
    form: {
      nameLabel: "Company name",
      namePlaceholder: "e.g. Yıldız Tekstil Ltd. Şti.",
      save: "Save",
      createError: "The company could not be created.",
    },
    analysis: {
      startingSoon: "The analysis will start shortly.",
      connectFirst: "Connect a data source first.",
      approvalTitle: "The analysis is waiting for your approval",
      confidenceLow:
        "The system was not sure about some lines, so it will not use the result without asking you.",
      confidenceWith:
        "The system's confidence in this analysis is {pct}%. Since the threshold is 80%, it will not use the result without asking you.",
      viewResults: "Let me see the results first",
      approveAndFinish: "Approve and finish",
      confirmTitle: "Do you approve this analysis?",
      confirmBody:
        "Approving marks this analysis as complete: the results are written into the company view and other analyses start using this data. Who approved it is recorded.",
      cancel: "Cancel",
      approve: "Approve",
      approveError: "Could not approve.",
      failedTitle: "The last analysis could not be completed",
      noReason: "No reason was recorded.",
      reconnect: "Reconnect the file",
      processing: "{file} is being processed…",
    },
  },
  kurumsallasma: {
    title: "Institutionalization Index",
    subtitle:
      "Your company's institutionalization level — authority delegation, decision traceability, human oversight, process rhythm, and key-person risk — on a 0–100 scale.",
    recompute: "Recompute",
    loadError: "Could not load",
    recomputeError: "Could not compute",
    gradeLabel: "grade: {grade}",
    trend: "Trend",
    measurements: "{count} measurements · last: {date}",
    dimensions: "Dimensions",
    weightLine: "{score} · weight {weight}%",
    recommendations: "Priority steps",
  },
  pilot: {
    title: "Pilot Program",
    subtitle: "Invite codes and user feedback",
    refresh: "Refresh",
    loadError: "Could not load data.",
    genericError: "Error",
    noData: "No data yet",
    npsOutOf: "/ 100 NPS",
    stats: {
      totalUsers: "Total users",
      maxUsers: "/ {max} max",
      freeSlots: "Free slots",
      pendingInvites: "Pending invites",
      usedInvites: "Used invites",
    },
    feedback: {
      summary: "Feedback summary ({count} responses)",
      npsScore: "NPS score",
      promoters: "{count} promoter",
      passives: "{count} passive",
      detractors: "{count} detractor",
      analysisQuality: "Analysis quality",
      accuracy: "Accuracy",
      usefulness: "Usefulness",
      topBenefits: "Most liked:",
      topGaps: "Most missed:",
    },
    generate: {
      heading: "Create invite code",
      emailPlaceholder: "Email (optional)",
      notePlaceholder: "Note (e.g. company name)",
      submit: "Create",
    },
    invites: {
      heading: "Invite codes ({count})",
      used: "Used",
      copyLink: "Copy link",
      revoke: "Revoke",
    },
    recent: {
      heading: "Recent feedback ({count})",
      npsBadge: "NPS {score}",
    },
    empty: {
      heading: "Pilot program has not started",
      body: "Create an invite code above and share it.",
    },
  },
  settingsAlerts: {
    title: "Alert settings",
    subtitle: "Route SLA breaches and critical agent alerts to Slack or email.",
    enable: "Enable outbound alerts",
    slackLabel: "Slack webhook URL",
    slackPlaceholder: "https://hooks.slack.com/services/…",
    emailLabel: "Email recipients (comma-separated)",
    emailPlaceholder: "ops@company.com",
    save: "Save",
    saving: "Saving…",
    saved: "Alert preferences saved.",
    savedLocal:
      "Saved locally (API unavailable). Configure SMTP/Slack in backend for delivery.",
    saveFailed: "Save failed",
  },
  settingsWorkspace: {
    title: "Workspace settings",
    subtitle: "Manage your organization and its members",
    loading: "Loading…",
    createWorkspace: "Create a workspace →",
    planBadge: "{plan} plan",
    memberCount: "{count} / {max} members",
    roles: {
      owner: "Owner",
      admin: "Admin",
      cfo: "CFO",
      analyst: "Analyst",
      viewer: "Viewer",
    },
    errors: {
      noWorkspace: "You are not a member of a workspace yet.",
      loadFailed: "An error occurred while loading data.",
      generic: "An error occurred.",
      inviteFailed: "The invite could not be sent.",
    },
    locale: {
      title: "Locale & Regional Packs",
      subtitle: "Currency, language, and country packs (e.g. Turkey SMMM / e-Fatura).",
      localeLabel: "Locale",
      currencyLabel: "Base currency",
      countryLabel: "Country",
      trPackTitle: "Turkey regional pack",
      trPackBody: "Enables THP CoA, SMMM approval queue, and e-Fatura flows.",
      save: "Save locale",
      saved: "Saved",
      saveFailed: "Save failed.",
    },
    localeOptions: {
      "en-US": "English (US)",
      "en-GB": "English (UK)",
      "tr-TR": "Türkçe",
      "de-DE": "Deutsch",
    },
    countries: {
      US: "United States",
      GB: "United Kingdom",
      TR: "Türkiye",
      DE: "Germany",
      AE: "UAE",
      SG: "Singapore",
    },
    semantic: {
      title: "Semantic company model",
      subtitle: "Reproject canonical metrics and decision brief from agent results + transactions.",
      rebuild: "Rebuild semantic model",
      rebuilt: "Rebuilt {count} metrics for {period}.",
      rebuildFailed: "Rebuild failed",
    },
    alerts: {
      loading: "Loading alert settings…",
      title: "Alert & notification settings",
      slack: {
        title: "Slack integration",
        body: "Send critical alerts and daily digests to your Slack channel.",
        howto: "How do I get a webhook URL?",
        webhookLabel: "Webhook URL",
        webhookPlaceholder: "https://hooks.slack.com/services/T.../B.../...",
        channelLabel: "Channel (optional)",
        channelPlaceholder: "#finance-alerts",
        test: "Send test message",
        testSent: "Test message sent!",
        testFailed: "Slack test failed — check the webhook URL.",
      },
      email: {
        label: "Email recipients",
        placeholder: "cfo@sirket.com, ceo@sirket.com",
        hint: "Separate multiple addresses with commas.",
      },
      severity: {
        label: "Minimum alert severity",
        info: "Info",
        warning: "Warning",
        critical: "Critical",
        hint: "Alerts below this level do not create notifications.",
      },
      digest: {
        title: "Daily digest",
        body: "A summary of all alerts is sent every morning at 08:00 UTC.",
      },
      save: "Save",
      saved: "Saved",
      saveFailed: "Save failed.",
    },
    members: {
      title: "Members ({count})",
      empty: "No members yet.",
      removeAria: "Remove {email}",
    },
    invite: {
      title: "Invite member",
      placeholder: "user@company.com",
      button: "Send invite",
      hint: "The invite link is automatically copied to your clipboard.",
    },
    pendingInvites: {
      title: "Pending invites ({count})",
      expiresAt: "{role} · until {date}",
      copyAria: "Copy link",
      cancelAria: "Cancel invite",
    },
  },
  tetikler: {
    title: "Trigger engine",
    subtitle:
      "When an event arrives and a condition holds, an action runs on its own. Rules are org-scoped and every evaluation is written to the audit log.",
    refresh: "Refresh",
    loading: "Loading triggers…",
    newRule: "New rule",
    editRule: "Edit rule",
    formName: "Rule name",
    formNamePlaceholder: "e.g. runway drops below 3 months",
    formEvents: "Event types",
    eventKinds: {
      jobCompleted: { label: "Analysis completed", hint: "When an analysis finishes; the condition reads that analysis's metrics." },
      txArrived: { label: "Transactions arrived", hint: "When new transactions land; the condition reads the company's latest metrics." },
      anomalyDetected: { label: "Anomaly detected", hint: "When a scan finds new anomalies; the same findings on a rescan do not fire again." },
      schedule: { label: "Daily check", hint: "Once a day (UTC); the condition reads the company's latest metrics." },
    },
    formCondition: "Condition",
    formConditionPlaceholder:
      '{"metric": "finance.runway_months", "op": "lt", "value": 3}',
    simpleEditor: "Switch to JSON editor",
    jsonEditor: "Back to simple editor",
    formAction: "Action",
    formCooldown: "Cooldown (min)",
    formParams: "Action params (JSON)",
    formParamsPlaceholder:
      '{"severity": "critical"}',
    formEnabled: "Enabled",
    submitCreate: "Create",
    submitSaving: "Saving…",
    submitUpdate: "Update",
    cancel: "Cancel",
    dryRunTitle: "Condition test (dry-run)",
    dryRunSubtitle:
      "Evaluate a condition against sample metric values. No action runs, nothing is written.",
    dryRunCondition: "Condition (JSON)",
    dryRunConditionPlaceholder:
      '{"metric": "finance.runway_months", "op": "lt", "value": 3}',
    dryRunValues: "Sample values (JSON)",
    dryRunButton: "Test",
    dryRunBusy: "Evaluating…",
    dryRunYes: "Would fire",
    dryRunNo: "Would not fire",
    dryRunUnknownMetrics:
      "Metrics missing from the catalog: {list} — a live run of this rule would sit at “condition false” forever.",
    dryRunLoadAria: "Load condition into the tester",
    rulesHeading: "Rules ({count})",
    rulesEmpty: "No rules yet. Create your first one with the form above.",
    colName: "Name",
    colEvents: "Events",
    colAction: "Action",
    colCooldown: "Cooldown",
    colEnabled: "Enabled",
    colLog: "",
    cooldownUnit: "{count} min",
    toggleEnable: "Disable",
    toggleDisable: "Enable",
    editAria: "Edit",
    deleteAria: "Delete",
    logAria: "Audit log",
    logFiltered: "filtered: {name}",
    logClearFilter: "Clear filter",
    logHeading: "Audit log",
    logFilteredHeading: "Audit log ({filter})",
    logEmpty: "No evaluations yet. Entries accumulate as events are processed.",
    colTime: "Time",
    colRule: "Rule",
    colEvent: "Event",
    colStatus: "Outcome",
    colDetail: "Detail",
    statusFired: "Fired",
    statusCooldown: "Cooling down",
    statusConditionFalse: "Condition not met",
    statusDuplicate: "Duplicate event",
    statusError: "Error",
    catalogHint: "{metrics} metrics, {scenarios} cascade scenarios defined.",
    errNameRequired: "Rule name is required.",
    errEventsRequired: "Pick at least one event type.",
    errConditionJson: "Condition JSON is not valid.",
    errParamsJson: "Action params JSON is not valid.",
    errValuesJson: "Sample values JSON is not valid.",
    errGeneric: "Something went wrong.",
    confirmDelete: "Delete the “{name}” rule? Its audit history is kept.",
    updated: "“{name}” updated.",
    created: "“{name}” created.",
    deleted: "“{name}” deleted.",
  },
};
