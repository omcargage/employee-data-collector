/**
 * WorkSense Single Source of Copy (strings.js)
 * All user-facing strings, technical definitions, tooltips, empty states, and error states.
 * Edit this file to update any application copy without modifying React code.
 */
window.WORK_SENSE_STRINGS = {
  brand: {
    name: "WorkSense",
    tagline: "Early-warning burnout prevention platform",
    researchNote: "Built as an interdisciplinary student research project at FLAME University, Pune.",
    zeroIdentificationStandard: "Strict Zero-Identification Standard. WHO-aligned burnout framework.",
    privateLockLine: "Only you can see this page.",
    managerLockLine: "Individual data is private to each employee.",
    demoModeSample: "Sample employees",
    demoModeLive: "Live app",
    roleEmployee: "Employee",
    roleManager: "Manager"
  },

  nav: {
    employee: {
      today: "Today",
      trends: "Metrics & telemetry",
      checkin: "Day Check-in",
      suggestions: "Suggestions",
      privacy: "Privacy & Data",
      about: "About WorkSense"
    },
    manager: {
      overview: "Overview",
      teams: "Teams",
      drivers: "Drivers",
      checkins: "Check-ins",
      actions: "Actions",
      reports: "Reports",
      admin: "Admin",
      about: "Privacy governance"
    }
  },

  status: {
    steady: {
      word: "Steady",
      colorName: "sage",
      sentence: "Your work pattern is steady and matching your usual pace. Keep up your balanced rhythm.",
      action: "Maintain your regular lunch and stretch blocks today."
    },
    stretched: {
      word: "Stretched",
      colorName: "sand",
      sentence: "Your work pattern has shifted a little from your usual. Nothing urgent, but protect your breaks this week.",
      action: "Block out a 15-minute quiet recovery window this afternoon."
    },
    strained: {
      word: "Strained",
      colorName: "terracotta",
      sentence: "Your work pattern shows noticeable strain building up across recent days. Prioritize recovery and protect your boundaries.",
      action: "End work at your scheduled shift time tonight with no late emails."
    },
    overloaded: {
      word: "Overloaded",
      colorName: "deep rose",
      sentence: "Your working rhythms show sustained high fatigue and boundary erosion. Consider speaking with your team and taking restorative rest.",
      action: "Speak with your team lead about workload rebalancing and step away for an extended pause."
    },
    calibrating: {
      word: "Learning your normal",
      title: "Baseline learning phase",
      sentence: "WorkSense is observing your desktop habits across typing pace, continuous focus stretches, and breaks to establish your personal baseline. No burnout status is generated during this 14-day calibration window.",
      noStatus: "No status today"
    }
  },

  tooltips: {
    bat12: {
      term: "BAT-12",
      label: "What is BAT-12?",
      short: "Burnout Assessment Tool (BAT-12)",
      description: "A clinically validated 12-item self-report questionnaire developed by Prof. Wilmar Schaufeli. It assesses 4 core burnout dimensions: Exhaustion, Mental distance, Cognitive impairment, and Emotional impairment."
    },
    baselineCalibration: {
      term: "14-day baseline",
      label: "What is baseline calibration?",
      short: "Personal 14-day baseline",
      description: "A 14-day observation window where WorkSense learns your unique typing pace, session lengths, and break habits without generating burnout predictions. Your normal is calibrated to you alone, never compared to team members."
    },
    kAnonymity: {
      term: "k-Anonymity (k >= 5)",
      label: "What is k-anonymity?",
      short: "Minimum group size (k >= 5)",
      description: "A mathematical privacy guarantee ensuring that any department or team with fewer than 5 members is completely hidden from managerial views, preventing any individual from ever being singled out."
    },
    zeroIdentification: {
      term: "Zero-identification",
      label: "What is zero-identification?",
      short: "Zero-Identification Protocol",
      description: "An architectural privacy boundary: WorkSense only analyzes timing intervals, counts, and statistical rhythm variations. It NEVER captures keystroke characters, reads messages, or inspects application window titles."
    },
    dwellTime: {
      term: "Key dwell time",
      label: "What is key dwell time?",
      short: "Key dwell time",
      description: "The microsecond duration a physical keyboard key remains depressed before release. Research shows that subtle changes in key dwell time indicate physical fatigue and strain."
    },
    grossWpm: {
      term: "Typing speed (WPM)",
      label: "What is typing speed evaluation?",
      short: "Typing speed pace",
      description: "Your active typing speed measured in words per minute. Deviations are evaluated against your personal baseline rather than a universal standard. Shown as 'changed' rather than 'worse' to avoid value judgment."
    },
    deviationScore: {
      term: "Deviation bands",
      label: "How are deviation bands calculated?",
      short: "Behavioral deviation bands",
      description: "How today's rhythm compares with your personal 14-day baseline: Typical (neutral), A bit different (amber), or Much different (soft rose)."
    },
    temporalNN: {
      term: "Temporal neural network",
      label: "How does the ML model predict?",
      short: "Bidirectional GRU neural network",
      description: "A deep learning temporal neural network that tracks rhythm sequences across multiple working days to detect chronic burnout risks 5+ working days in advance of acute exhaustion."
    },
    shiftMidpoint: {
      term: "Shift midpoint",
      label: "What is the shift midpoint rule?",
      short: "Shift midpoint rule",
      description: "The midpoint of your scheduled workday (defaults to 1:00 PM). WorkSense unlocks the daily check-in at this time so that your self-reported score accurately reflects your workday experience."
    },
    quietHours: {
      term: "Quiet hours",
      label: "What are quiet hours?",
      short: "Quiet hours schedule",
      description: "A scheduled daily window (such as 12:30 PM - 1:30 PM lunch, or after 7:00 PM) during which desktop nudges and non-urgent prompts are suppressed to protect focus and rest."
    }
  },

  today: {
    greetingEvening: "Good evening",
    greetingMorning: "Good morning",
    greetingAfternoon: "Good afternoon",
    liveDotLabel: "Live data",
    outlookTitle: "Your next 5 working days",
    howWorkedOut: "How is this worked out?",
    confidenceLabel: "Confidence",
    riskIndexLabel: "Risk index",
    contributorsTitle: "What's behind this",
    topContributorsSubtitle: "Ranked factors shaping your current outlook",
    comparesTitle: "How today compares with your usual",
    comparesSubtitle: "Top 3 deviating metrics against your personal 14-day baseline",
    suggestionTitle: "Suggestion for you",
    sevenDayTitle: "Your last 7 days",
    onlyYouCanSee: "Only you can see this page.",
    earlyLoggingOff: "Logging off early? Check in now.",
    takeCheckinButton: "Take today's check-in (about 2 minutes)"
  },

  metrics: {
    title: "Metrics & telemetry",
    subtitle: "Rhythms, rest pauses, typing pace, and pointer dynamics",
    tabs: {
      rhythm: "Work rhythm",
      afterHours: "After-hours",
      typing: "Typing",
      mouse: "Mouse"
    },
    toggle7Days: "7 days",
    toggle30Days: "30 days",
    viewDataButton: "View data",
    tableHeading: "Your last 7 days",
    exportCsvButton: "Export CSV",
    tableColumns: {
      date: "Date",
      stretch: "Longest stretch",
      lunch: "Midday break",
      afterHours: "After-hours msgs",
      wpm: "Typing speed",
      corrections: "Corrections",
      checkin: "Check-in"
    }
  },

  checkin: {
    cardTitle: "How was your day?",
    pageTitle: "Day Check-in",
    pageSubtitle: "Scientific Burnout Assessment Tool (BAT-12) telemetry history",
    lockedBefore1Pm: "Opens at 1:00 PM so it reflects your day.",
    doneToday: "Done today ✓",
    usualScorePrefix: "Your usual check-in score",
    scaleLabels: ["Never", "Rarely", "Sometimes", "Often", "Always"],
    skipItem: "Skip this question",
    unskipItem: "Rate this question",
    stepPrefix: "Step",
    ofText: "of",
    previousStep: "Previous",
    nextStep: "Next step",
    submitButton: "Submit today's check-in",
    submitting: "Submitting..."
  },

  suggestions: {
    title: "Suggestions for you",
    subtitle: "Personalized desktop recovery prompts based on your work rhythm deviations",
    tabs: {
      active: "Active suggestions",
      past: "History",
      preferences: "Preferences"
    },
    buttons: {
      done: "Done",
      snooze: "Snooze",
      notHelpful: "Not helpful"
    },
    preferences: {
      frequencyTitle: "Suggestion frequency",
      quietHoursTitle: "Quiet hours",
      muteTodayTitle: "Mute for today"
    }
  },

  privacy: {
    title: "Privacy & Data",
    subtitle: "Strict zero-identification architecture, local workstation storage, and data controls",
    whatWeCollectTitle: "What we collect",
    whatWeCollectSubtitle: "Timings and rhythm counts only — never what you type or the content of messages",
    whoSeesWhatTitle: "Who sees what",
    youSeeEverything: "You: everything",
    managerSeesAggregates: "Your manager: team-level summaries only, never your individual data",
    pauseTracking: "Pause tracking",
    exportData: "Export my data",
    deleteData: "Delete my data"
  },

  manager: {
    overview: {
      title: "Team overview",
      subtitle: "Aggregated organizational workload, strain distribution, and participation trends.",
      teamStatusMixTitle: "Team status mix",
      changeVsLastWeekTitle: "Change vs last week",
      checkinParticipationTitle: "Check-in participation",
      fourWeekOutlookTitle: "4-week strain outlook",
      shareElevatedTitle: "Share of employees in Strained or Overloaded",
      benchmarkLabel: "20% organizational benchmark",
      insufficientGroupTitle: "Not enough people to show this group",
      insufficientGroupSubtitle: "To protect individual psychological safety, groups with fewer than 5 members cannot be displayed."
    },
    teams: {
      title: "Teams and departments",
      subtitle: "Departmental breakdown with active status mix, rolling 4-week trend, and minimum group size protection.",
      totalMonitored: "Total monitored",
      activeTeams: "Active reporting teams",
      protectedTeams: "Protected (fewer than 5 people)",
      viewOverviewButton: "View overview →"
    },
    drivers: {
      title: "Behavioral drivers",
      subtitle: "Broad categories only. Aggregate workload patterns contributing to team strain.",
      categoriesPrivacyCallout: "Broad categories privacy guarantee: To ensure zero individual tracking, WorkSense aggregates telemetry into four systemic work dimensions. No keystrokes, message texts, or individual names are ever inspected or stored."
    },
    checkins: {
      title: "Daily check-in telemetry",
      subtitle: "Aggregate Burnout Assessment Tool (BAT-12) participation, score distribution, and clinical burnout domains.",
      scoreDistributionTitle: "Aggregate check-in score distribution",
      domainBreakdownTitle: "BAT-12 domain breakdown"
    },
    actions: {
      title: "Suggested interventions & action tracker",
      subtitle: "Targeted organizational initiatives, real-time status tracker, and before/after status mix evaluation.",
      beforeAfterTitle: "Before / after intervention status mix",
      suggestedInterventionsTitle: "Suggested organizational interventions",
      updateTrackerLabel: "Update tracker:"
    },
    reports: {
      title: "Stress level reports & summaries",
      subtitle: "Scheduled dispatches and on-demand PDF/email summaries of team stress levels.",
      generateTitle: "Generate team stress summary",
      generateButton: "Generate report",
      generatingButton: "Generating report...",
      scheduledTitle: "Scheduled email and PDF dispatches",
      archiveTitle: "Past generated stress summaries"
    },
    admin: {
      title: "Admin & organizational settings",
      subtitle: "Working hours and holidays, team setup, and an audit log of who viewed what and when.",
      workingHoursTitle: "Working hours & rhythm thresholds",
      holidaysTitle: "Observed holidays 2026",
      teamSetupTitle: "Team setup & privacy threshold status",
      auditLogTitle: "Access audit log",
      searchPlaceholder: "Search audit events..."
    }
  },

  states: {
    loading: {
      title: "Loading data...",
      description: "Retrieving telemetry and evaluating rhythm patterns."
    },
    empty: {
      defaultTitle: "No data available",
      defaultDescription: "There is no recorded information for this section yet.",
      noActivityToday: "No activity recorded today",
      noActivityDescription: "We haven't received telemetry for this workday yet. Data will appear once active desktop sessions are detected.",
      noPastReports: "No past reports found",
      noPastReportsDescription: "Generate your first on-demand report using the controls above.",
      noAuditLogs: "No matching audit events",
      noAuditLogsDescription: "Try adjusting your search query or check back later."
    },
    error: {
      title: "Unable to load telemetry",
      description: "An error occurred while connecting to the local WorkSense bridge server.",
      retryButton: "Try again",
      offlineTip: "Please ensure desktop.py or start_worksense.bat is active on your workstation."
    }
  }
};
