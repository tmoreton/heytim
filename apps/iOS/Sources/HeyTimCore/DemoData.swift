import Foundation

#if DEBUG
public enum DemoData {
  public static let constraints = AppConstraints(
    botNameMaxLength: 60, botTaglineMaxLength: 160, botPromptMaxLength: 20_000,
    groupNameMaxLength: 80, groupMemoryMaxLength: 20_000, messageMaxLength: 20_000,
    scheduleNameMaxLength: 100, schedulePromptMaxLength: 20_000,
    scheduleDayOfMonthMin: 1, scheduleDayOfMonthMax: 28,
    skillNameMaxLength: 80, skillDescriptionMaxLength: 500, skillInstructionsMaxLength: 30_000,
    memoryMaxLength: 2_000, maxAttachmentsPerMessage: 10, maxToolsPerBot: 13,
    imageMaxBytes: 20_000_000, documentMaxBytes: 50_000_000, maxPhotoDimension: 4096
  )
  public static let tools = [
    Capability(
      id: "web_search", name: "Web Search",
      description: "Find current information from public web sources.", risk: "read",
      category: "Research", actions: ["Search the web", "Open public pages"],
      source: "official"),
    Capability(
      id: "code_interpreter", name: "Files & Data",
      description: "Analyze data and create useful documents.", risk: "interactive",
      category: "Files", actions: ["Analyze files", "Create documents"],
      source: "official"),
  ]
  private static let demoConnectionProviders = [
    ConnectionProvider(
      id: "x", name: "X",
      description: "Search posts and read your profile with a connected X account.",
      category: "Social", iconText: "X",
      permissionsSummary: "Read-only account access",
      privacyTitle: "Your X account stays private",
      privacyDescription: "Connect an account before a bot can search X.",
      familyId: "x", familyName: "X",
      familyDescription: "Connect an X account for search and profile access.",
      familyIconText: "X", familyLogoProviderId: "x",
      serviceName: "Account access"),
    ConnectionProvider(
      id: "youtube", name: "YouTube",
      description: "Search public videos with your connected YouTube account; channel tools are optional.",
      category: "Social", iconText: "YT",
      permissionsSummary: "Read-only YouTube account access",
      privacyTitle: "How your YouTube data is used",
      privacyDescription: "Assigned bots may send relevant channel data through OpenRouter to an AI provider and save it in conversations or memory.",
      familyId: "youtube", familyName: "YouTube",
      familyDescription: "Connect an account for YouTube search.",
      familyIconText: "YT", familyLogoProviderId: "youtube",
      serviceName: "YouTube account"),
    ConnectionProvider(
      id: "mcp_server", name: "MCP server",
      description: "Connect a remote MCP server by HTTPS URL and access token.",
      category: "Integrations", iconText: "MCP",
      permissionsSummary: "The selected bot can use tools exposed by this server",
      privacyTitle: "Assign each server only to bots that need it",
      privacyDescription: "The access token is stored privately on the server.",
      familyId: "mcp", familyName: "MCP servers",
      familyDescription: "Add multiple trusted MCP servers and assign each one to specific bots.",
      familyIconText: "MCP", familyLogoProviderId: "mcp_server"),
    ConnectionProvider(
      id: "gmail", name: "Gmail",
      description: "Search and summarize email, then create drafts for review.",
      category: "Email", iconText: "G",
      permissionsSummary: "No sending, deleting, relabeling, or archiving",
      privacyTitle: "How your Gmail data is used",
      privacyDescription: "Assigned bots may send relevant email through OpenRouter to an AI provider and save it in conversations or memory.",
      familyId: "google", familyName: "Google",
      familyDescription: "Connect the Google account each bot needs for Gmail.",
      familyIconText: "G", familyLogoProviderId: "gmail",
      serviceName: "Gmail"),
    ConnectionProvider(
      id: "google_workspace", name: "Google Workspace",
      description: "Search and read Drive files, Docs, and Calendar events.",
      category: "Productivity", iconText: "GW",
      permissionsSummary: "Read-only Drive, Docs, and Calendar access",
      privacyTitle: "Workspace content stays user-scoped",
      privacyDescription: "It cannot change files or calendar events.",
      familyId: "google", familyName: "Google",
      familyDescription: "Connect the Google accounts each bot needs.",
      familyIconText: "G", familyLogoProviderId: "google_workspace",
      serviceName: "Workspace"),
  ]
  public static let skills = [
    Skill(
      id: "deep-research", name: "Deep Research",
      description: "Produce a current, sourced, decision-ready synthesis.",
      category: "Research", featured: true, version: 1,
      requiredToolIds: ["web_search", "code_interpreter"], source: "official",
      visibility: "public", editable: false)
  ]
  public static let botTemplates = [
    BotTemplate(
      id: "research-reports", version: 1, name: "Research & Reports",
      tagline: "Finds reliable answers and turns them into useful files.",
      prompt:
        "Research broad questions with current, high-quality sources and lead with the conclusion. Distinguish evidence from interpretation and create a polished report when it helps.",
      color: "#5C6BC0", skillIds: ["deep-research"], toolIds: [],
      category: "Research", author: "Hey Tim", tags: ["research", "reports"],
      featured: true)
  ]
  public static let bootstrap = Bootstrap(
    bots: [
      Bot(
        id: "chief", name: "Chief", tagline: "Your capable AI chief of staff", color: "#FFBC3B",
        prompt: "Help thoughtfully.", toolIds: [], skillIds: [],
        systemRole: "chief",
        createdAt: "2026-09-12T12:00:00.000Z", updatedAt: "2026-09-12T12:00:00.000Z",
        lastMessage: "Your project brief is ready.", lastMessageAt: "2026-09-12T12:01:00.000Z",
        allowedActions: ["schedule", "share", "documents", "browser", "edit", "clear", "delete"])
    ],
    botTemplates: botTemplates, connectionProviders: demoConnectionProviders,
    needsBotOnboarding: false, groups: [], tools: tools,
    retiredToolIds: [], skills: skills, constraints: constraints,
    aiSharingConsent: AISharingConsent(version: 1, granted: true)
  )
  public static var multipleConnectionsBootstrap: Bootstrap {
    var value = bootstrap
    value.tools += [
      Capability(
        id: "connection_gmail_alpha", name: "Gmail",
        description: "Read and draft email.", provider: "gmail", source: "user",
        connectedAccount: "alpha@example.com"),
      Capability(
        id: "connection_gmail_beta", name: "Gmail",
        description: "Read and draft email.", provider: "gmail", source: "user",
        connectedAccount: "beta@example.com"),
      Capability(
        id: "connection_github_team", name: "GitHub",
        description: "Read connected repositories.", provider: "github", source: "user",
        connectedAccount: "team", repositories: [
          ConnectedRepository(id: 101, name: "team/api"),
          ConnectedRepository(id: 102, name: "team/app"),
        ]),
    ]
    value.connectionProviders.append(
      ConnectionProvider(
        id: "github", name: "GitHub", description: "Read connected repositories.",
        category: "Development", iconText: "GH",
        permissionsSummary: "Read-only repository access",
        privacyTitle: "Choose repositories for each bot",
        privacyDescription: "Only selected repositories are available."))
    return value
  }
  public static var twoBotsBootstrap: Bootstrap {
    var value = bootstrap
    value.bots.append(
      Bot(
        id: "researcher", name: "Research Bot", tagline: "Investigates questions",
        color: "#3488E8", prompt: "Research carefully.", toolIds: [], skillIds: [],
        createdAt: "2026-09-12T12:02:00.000Z", updatedAt: "2026-09-12T12:02:00.000Z",
        lastMessage: "Ready to research.", lastMessageAt: "2026-09-12T12:03:00.000Z",
        allowedActions: ["schedule", "share", "documents", "browser", "edit", "clear", "delete"]))
    return value
  }
  public static let messages = [
    ChatMessage(
      id: "m1", role: "user", authorName: "You", isMine: true,
      text: "Can you summarize the launch plan?", createdAt: "2026-09-12T12:00:00.000Z",
      status: "complete"),
    ChatMessage(
      id: "m2", role: "assistant", authorType: "bot", authorId: "chief", authorName: "Chief",
      authorColor: "#FFBC3B",
      text:
        "Absolutely. The native SwiftUI client is sharing the same backend and API contract across iPhone and Mac.\n\n- Authentication and data stay in AWS.\n- Conversations and background tasks are preserved.\n- The existing web app remains available.",
      createdAt: "2026-09-12T12:01:00.000Z", status: "complete"),
  ]
  public static let scrollMessages = (1...24).map { index in
    ChatMessage(
      id: "scroll-\(index)", role: index.isMultiple(of: 2) ? "assistant" : "user",
      authorType: index.isMultiple(of: 2) ? "bot" : "user",
      authorName: index.isMultiple(of: 2) ? "Chief" : "You",
      authorColor: index.isMultiple(of: 2) ? "#FFBC3B" : nil,
      isMine: !index.isMultiple(of: 2),
      text: index == 24
        ? "Latest message before send."
        : "Conversation history item \(index) with enough detail to exercise scrolling.",
      createdAt: "2026-09-12T12:\(String(format: "%02d", index)):00.000Z",
      status: "complete")
  }
  public static var delayedResearchMessages: [ChatMessage] {
    var value = scrollMessages
    value[value.count - 1].text = String(
      repeating: "A researched detail that makes this response taller than the screen.\n\n",
      count: 18) + "Research Bot answer visible after loading."
    return value
  }
  public static let activityMessages = [
    ChatMessage(
      id: "activity-user", role: "user", isMine: true,
      text: "Please inspect the project and summarize what needs attention.",
      createdAt: "2026-09-12T12:02:00.000Z", status: "complete"),
    ChatMessage(
      id: "activity-assistant", role: "assistant", authorType: "bot", authorId: "chief",
      authorName: "Chief", authorColor: "#FFBC3B", text: "",
      activity: [
        "Reviewing the repository structure and current branch.",
        "Checking `README.md` for the intended release workflow.",
        "Inspecting the native conversation layout and message state.",
        "Comparing API routes with the generated client contract.",
        "Checking notification delivery and account cleanup behavior.",
        "Reviewing attachment handling for images and documents.",
        "Verifying session changes cannot leak drafts between accounts.",
        "Running the focused native test suite.",
        "Checking the final build for embedded framework duplication.",
        "Preparing the verified summary and recommended follow-up.",
      ],
      createdAt: "2026-09-12T12:02:01.000Z", activityUpdatedAt: "2026-09-12T12:02:10.000Z",
      status: "running"),
  ]
  public static var completedActivityMessages: [ChatMessage] {
    var value = activityMessages
    value[1].status = "complete"
    value[1].text = "Hey Tim test passed."
    value[1].usageSummary = ChatUsageSummary(
      modelIds: ["test/model"], callCount: 1, inputTokens: 120, outputTokens: 40,
      cacheReadInputTokens: 0, cacheReportAvailable: false, costUsd: "0.0012",
      costBasis: "estimated", costIncomplete: false, reasoningEffort: "medium")
    return value
  }
  public static let groupProgressGroup = BotGroup(
    id: "research-team", name: "Research Team", memory: "", memoryUpdatedAt: nil,
    memoryUpdatedByName: nil, ownerId: "owner", currentUserId: "owner", isOwner: true,
    allowedActions: ["schedule", "share", "viewMemory", "manageMemory", "edit", "clear", "delete"],
    members: [
      GroupMember(id: "owner", name: "You", role: "owner", allowedActions: [])
    ],
    bots: [
      GroupBot(
        id: "researcher", ownerId: "owner", name: "YouTube Research",
        tagline: "Researches source material", color: "#3488E8", systemRole: nil),
      GroupBot(
        id: "chief", ownerId: "owner", name: "Chief", tagline: "Coordinates the team",
        color: "#FFBC3B", systemRole: "chief"),
      GroupBot(
        id: "reviewer", ownerId: "owner", name: "Reviewer", tagline: "Checks the result",
        color: "#6C5CE7", systemRole: nil),
    ], decisions: [], createdAt: "2026-09-13T11:00:00.000Z",
    updatedAt: "2026-09-13T11:00:00.000Z", lastMessage: "Researching the request",
    lastMessageAt: "2026-09-13T11:00:00.000Z", processing: true,
    processingBotName: "YouTube Research")
  public static var groupProgressBootstrap: Bootstrap {
    var value = bootstrap
    value.groups = [groupProgressGroup]
    return value
  }
  public static var historySwitchBootstrap: Bootstrap {
    var value = twoBotsBootstrap
    var group = groupProgressGroup
    group.processing = false
    group.processingBotName = nil
    value.groups = [group]
    return value
  }
  public static let historySwitchGroupMessages = [
    ChatMessage(
      id: "history-group-user", role: "user", authorName: "You", isMine: true,
      text: "Group conversation history before switching.",
      createdAt: "2026-09-13T11:00:00.000Z", status: "complete"),
    ChatMessage(
      id: "history-group-reply", role: "assistant", authorType: "bot", authorId: "chief",
      authorName: "Chief", authorColor: "#FFBC3B",
      text: "Group answer remains available after switching.",
      createdAt: "2026-09-13T11:01:00.000Z", status: "complete"),
  ]
  public static let historySwitchResearchMessages = [
    ChatMessage(
      id: "history-research-user", role: "user", authorName: "You", isMine: true,
      text: "Research Bot conversation history before switching.",
      createdAt: "2026-09-13T12:00:00.000Z", status: "complete"),
    ChatMessage(
      id: "history-research-reply", role: "assistant", authorType: "bot",
      authorId: "researcher", authorName: "Research Bot", authorColor: "#3488E8",
      text: "Research Bot answer remains available after switching.",
      createdAt: "2026-09-13T12:01:00.000Z", status: "complete"),
  ]
  public static let groupProgressMessages = [
    ChatMessage(
      id: "group-request", role: "user", authorType: "user", authorName: "You", isMine: true,
      text: "Research the launch options and recommend the best approach.",
      createdAt: "2026-09-13T11:00:00.000Z", status: "complete"),
    ChatMessage(
      id: "group-running", role: "assistant", authorType: "bot", authorId: "researcher",
      authorName: "YouTube Research", authorColor: "#3488E8", text: "",
      activity: [
        "Reviewing the available source material.",
        "Comparing the strongest options and supporting evidence.",
      ], roundId: "round-1", roundPosition: 1, roundSize: 3, roundRole: "contributor",
      createdAt: "2026-09-13T11:00:01.000Z", status: "running"),
    ChatMessage(
      id: "group-pending", role: "assistant", authorType: "bot", authorId: "chief",
      authorName: "Chief", authorColor: "#FFBC3B", text: "", roundId: "round-1",
      roundPosition: 2, roundSize: 3, roundRole: "synthesizer",
      createdAt: "2026-09-13T11:00:02.000Z", status: "pending"),
    ChatMessage(
      id: "group-waiting", role: "assistant", authorType: "bot", authorId: "reviewer",
      authorName: "Reviewer", authorColor: "#FFBC3B", text: "", roundId: "round-1",
      roundPosition: 3, roundSize: 3, roundRole: "contributor",
      createdAt: "2026-09-13T11:00:03.000Z", status: "waiting"),
  ]
  public static let markdownMessages = [
    ChatMessage(
      id: "markdown-assistant", role: "assistant", authorType: "bot", authorId: "chief",
      authorName: "Chief", authorColor: "#FFBC3B",
      text: """
        ## Release check

        The **important details** now render cleanly.

        1. Open the pull request.
        2. Verify `main` before release.

        | Item | Status |
        | :--- | ---: |
        | Credentials | Protected |
        """,
      createdAt: "2026-09-12T12:03:00.000Z", status: "complete")
  ]
}
#endif
