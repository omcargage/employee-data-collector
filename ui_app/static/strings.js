/**
 * WorkSense Single Source of Copy (strings.js)
 * All user-facing strings, plain-English definitions, tooltips, empty states, error states, and authentication.
 * Plain, warm, human language across the entire application without medical or robotic jargon.
 */
window.WORK_SENSE_STRINGS = {
  brand: {
    name: "WorkSense",
    tagline: "Early-warning burnout prevention platform",
    researchNote: "Built as an interdisciplinary student research project at FLAME University, Pune.",
    zeroIdentificationStandard: "100% private. We never record keystrokes, messages, or screen content.",
    privateLockLine: "Only you can see this page.",
    managerLockLine: "Individual data is private to each employee.",
    demoModeSample: "Sample employees",
    demoModeLive: "Live app",
    roleEmployee: "Employee",
    roleManager: "Manager"
  },

  auth: {
    loginTitle: "Sign in to Live App",
    loginSubtitle: "Connect to your local workstation to view private, real-time work rhythm data.",
    emailLabel: "Work Email",
    passwordLabel: "Password",
    signInButton: "Sign In to Live App",
    cancelButton: "Cancel",
    logoutButton: "Log out",
    credentialsHint: "Evaluation Account: omkar.gage@worksense.flame  •  Password: IMPOML",
    errorInvalid: "Invalid email or password. Please use omkar.gage@worksense.flame and password IMPOML."
  },

  nav: {
    employee: {
      today: "Today",
      trends: "Work habits & metrics",
      checkin: "Day Check-in",
      suggestions: "Suggestions",
      privacy: "Privacy & Data",
      about: "About WorkSense"
    },
    manager: {
      overview: "Overview",
      teams: "Teams",
      drivers: "Work pressure factors",
      checkins: "Check-ins",
      actions: "Actions",
      reports: "Reports",
      admin: "Admin",
      about: "Privacy & ethics"
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
      sentence: "WorkSense is getting to know your typical typing speed, focus stretches, and break habits to establish your personal baseline. No burnout status is generated during this 14-day calibration window.",
      noStatus: "No status today"
    }
  },

  tooltips: {
    bat12: {
      term: "Daily check-in survey",
      label: "What is the daily check-in?",
      short: "Daily check-in survey",
      description: "A 12-question check-in based on established workplace research. It reflects on four simple areas of your day: physical tiredness, motivation, mental focus, and daily stress."
    },
    baselineCalibration: {
      term: "14-day baseline",
      label: "How does WorkSense learn your normal?",
      short: "Getting to know your habits",
      description: "During your first 14 days, WorkSense quietly learns your unique typing speed, focus stretches, and break habits. It never generates burnout alerts during this time, and your habits are never compared with anyone else."
    },
    kAnonymity: {
      term: "Privacy protection (5+ people)",
      label: "Why are small teams hidden?",
      short: "Hidden for privacy (5+ people)",
      description: "To protect everyone's privacy, any team or group with fewer than 5 people is hidden from manager views so no individual can ever be singled out."
    },
    zeroIdentification: {
      term: "100% private by design",
      label: "How is your privacy protected?",
      short: "100% Private by Design",
      description: "WorkSense only measures timing rhythms, break lengths, and pace. It NEVER reads what you type, never reads emails or messages, and never captures your screen."
    },
    dwellTime: {
      term: "Key hold time",
      label: "What is key hold time?",
      short: "Key hold time",
      description: "How long a keyboard key stays pressed down. Subtle changes in key hold time over days can indicate rising fatigue and muscle tension."
    },
    grossWpm: {
      term: "Typing speed",
      label: "What is typing speed?",
      short: "Typing speed",
      description: "How fast you type in words per minute. We only compare this against your own normal pace, never against coworkers."
    },
    deviationScore: {
      term: "Daily rhythm comparison",
      label: "How are differences shown?",
      short: "Daily rhythm comparison",
      description: "How today compares with your usual rhythm: Typical (normal), A bit different, or Much different."
    },
    temporalNN: {
      term: "Early warning system",
      label: "How does WorkSense spot early warning signs?",
      short: "Early warning system",
      description: "A smart pattern recognition system that looks at gentle changes in your work habits over several days to spot heavy fatigue before it happens, giving you time to recover."
    },
    shiftMidpoint: {
      term: "Midday check-in unlock",
      label: "When does the check-in unlock?",
      short: "Midday check-in unlock",
      description: "The daily check-in unlocks at 1:00 PM so your responses accurately reflect your workday experience."
    },
    quietHours: {
      term: "Quiet hours",
      label: "What are quiet hours?",
      short: "Quiet hours schedule",
      description: "A scheduled window (such as 12:30 PM - 1:30 PM lunch, or after 7:00 PM) where desktop suggestions are silenced to protect your focus and rest."
    }
  },

  today: {
    greetingEvening: "Good evening",
    greetingMorning: "Good morning",
    greetingAfternoon: "Good afternoon",
    liveDotLabel: "Live app",
    outlookTitle: "Your 5-day energy outlook",
    howWorkedOut: "How is this worked out?",
    confidenceLabel: "Confidence",
    riskIndexLabel: "Risk index",
    contributorsTitle: "What's shaping your outlook",
    topContributorsSubtitle: "Key factors shaping your current energy outlook",
    comparesTitle: "How today compares with your usual",
    comparesSubtitle: "Top 3 noticeable differences compared to your normal habits",
    suggestionTitle: "Suggestion for you",
    sevenDayTitle: "Your last 7 days",
    onlyYouCanSee: "Only you can see this page.",
    earlyLoggingOff: "Logging off early? Check in now.",
    takeCheckinButton: "Take today's check-in (about 2 minutes)"
  },

  metrics: {
    title: "Work habits & metrics",
    subtitle: "Focus stretches, rest breaks, typing pace, and mouse activity",
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
      stretch: "Longest stretch without break",
      lunch: "Lunch break",
      afterHours: "Late-day messages",
      wpm: "Typing speed",
      corrections: "Backspaces & edits",
      checkin: "Daily check-in"
    }
  },

  checkin: {
    cardTitle: "How was your day?",
    pageTitle: "Day Check-in",
    pageSubtitle: "Your daily 2-minute check-in history",
    lockedBefore1Pm: "Opens at 1:00 PM so it reflects your day.",
    doneToday: "Done today ✓",
    usualScorePrefix: "Your usual check-in",
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
    subtitle: "Helpful desktop recovery tips based on your work rhythm",
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
    subtitle: "100% private design, local storage on your machine, and complete data controls",
    whatWeCollectTitle: "What we track",
    whatWeCollectSubtitle: "Timing intervals and rhythm counts only — never what you type, write, or see on screen",
    whoSeesWhatTitle: "Who sees what",
    youSeeEverything: "You: everything",
    managerSeesAggregates: "Your manager: overall team summaries only, never your individual data",
    pauseTracking: "Pause tracking",
    exportData: "Export my data",
    deleteData: "Delete my data"
  },

  manager: {
    overview: {
      title: "Team overview",
      subtitle: "Overall team energy, workload balance, and participation trends.",
      teamStatusMixTitle: "Team energy status mix",
      changeVsLastWeekTitle: "Change vs last week",
      checkinParticipationTitle: "Check-in participation",
      fourWeekOutlookTitle: "4-week team pressure trend",
      shareElevatedTitle: "Share of team facing heavy pressure",
      benchmarkLabel: "20% healthy benchmark",
      insufficientGroupTitle: "Not enough people to show this group",
      insufficientGroupSubtitle: "To protect individual privacy, groups with fewer than 5 members are hidden."
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
      title: "Work pressure factors",
      subtitle: "Broad categories only. Key work habits contributing to team pressure.",
      categoriesPrivacyCallout: "Privacy guarantee: To ensure no individual is ever tracked, WorkSense groups work patterns into four broad categories. No keystrokes, messages, or names are ever recorded or displayed."
    },
    checkins: {
      title: "Daily check-in summaries",
      subtitle: "Overall check-in participation, score distribution, and wellbeing categories.",
      scoreDistributionTitle: "Overall check-in score distribution",
      domainBreakdownTitle: "Wellbeing categories"
    },
    actions: {
      title: "Suggested team actions & tracker",
      subtitle: "Team-wide initiatives, status tracker, and before/after energy comparison.",
      beforeAfterTitle: "Before / after team status",
      suggestedInterventionsTitle: "Suggested team actions",
      updateTrackerLabel: "Update tracker:"
    },
    reports: {
      title: "Team wellbeing reports",
      subtitle: "Scheduled and on-demand summaries of overall team energy and pressure.",
      generateTitle: "Create team wellbeing summary",
      generateButton: "Generate report",
      generatingButton: "Generating report...",
      scheduledTitle: "Scheduled email and PDF summaries",
      archiveTitle: "Past summaries"
    },
    admin: {
      title: "Admin & workspace settings",
      subtitle: "Standard working hours, holidays, team setup, and an audit log of who viewed what and when.",
      workingHoursTitle: "Standard working hours",
      holidaysTitle: "Observed holidays 2026",
      teamSetupTitle: "Teams & privacy protection status",
      auditLogTitle: "Access audit log",
      searchPlaceholder: "Search audit events..."
    }
  },

  states: {
    loading: {
      title: "Loading data...",
      description: "Retrieving your recent work rhythm data."
    },
    empty: {
      defaultTitle: "No data available",
      defaultDescription: "There is no recorded information for this section yet.",
      noActivityToday: "No activity recorded today",
      noActivityDescription: "We haven't recorded activity for today yet. Data will appear once you begin working.",
      noPastReports: "No past reports found",
      noPastReportsDescription: "Generate your first summary using the button above.",
      noAuditLogs: "No matching audit events",
      noAuditLogsDescription: "Try adjusting your search query or check back later."
    },
    error: {
      title: "Unable to load data",
      description: "Could not connect to the local WorkSense background app.",
      retryButton: "Try again",
      offlineTip: "Please ensure desktop.py or worksense.bat is active on your computer."
    }
  }
};
