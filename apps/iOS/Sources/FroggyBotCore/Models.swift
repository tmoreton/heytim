import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

public enum ConversationKind: String, Codable, Sendable { case bot, group }

public struct ConversationSelection: Hashable, Codable, Identifiable, Sendable {
  public let kind: ConversationKind
  public let id: String
  public init(kind: ConversationKind, id: String) {
    self.kind = kind
    self.id = id
  }
}

public struct Bot: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var tagline: String
  public var color: String
  public var prompt: String
  public var toolIds: [String]
  public var extraToolIds: [String]?
  public var alwaysAllowedToolIds: [String]?
  public var githubRepositoryAccess: [String: [Int]]?
  public var jiraProjectAccess: [String: [String]]?
  public var teamsChannelAccess: [String: [String]]?
  public var resourceAccess: [String: [String]]?
  public var skillIds: [String]
  public var templateId: String?
  public var templateVersion: Int?
  public var systemRole: String?
  public var createdAt: String
  public var updatedAt: String
  public var lastMessage: String
  public var lastMessageAt: String
  public var processing: Bool?
  public var processingBotName: String?
  public var allowedActions: [String]?
}

public struct BotDraft: Codable, Equatable, Sendable {
  public var name = ""
  public var tagline = ""
  // Chief owns FroggyBot green. New custom bots start with the service's supported teal.
  public var color = "#58BEAA"
  public var prompt = ""
  public var toolIds: [String] = []
  public var skillIds: [String] = []
  public var alwaysAllowedToolIds: [String] = []
  // An absent installation uses all repositories granted to that connection.
  public var githubRepositoryAccess: [String: [Int]] = [:]
  public var jiraProjectAccess: [String: [String]] = [:]
  public var teamsChannelAccess: [String: [String]] = [:]
  public var resourceAccess: [String: [String]] = [:]

  public init() {}
  public init(bot: Bot) {
    name = bot.name
    tagline = bot.tagline
    color = bot.color
    prompt = bot.prompt
    toolIds = bot.toolIds
    skillIds = bot.skillIds
    alwaysAllowedToolIds = bot.alwaysAllowedToolIds ?? []
    githubRepositoryAccess = bot.githubRepositoryAccess ?? [:]
    jiraProjectAccess = bot.jiraProjectAccess ?? [:]
    teamsChannelAccess = bot.teamsChannelAccess ?? [:]
    resourceAccess = bot.resourceAccess ?? [:]
  }
}

public struct BotTemplate: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var version: Int
  public var name: String
  public var tagline: String
  public var prompt: String
  public var color: String
  public var skillIds: [String]
  public var toolIds: [String]
  public var category: String?
  public var author: String?
  public var tags: [String]?
  public var featured: Bool?
  public var updatedAt: String?

  public func effectiveToolIDs(skills: [Skill]) -> [String] {
    let skillsByID = Dictionary(uniqueKeysWithValues: skills.map { ($0.id, $0) })
    var seen = Set<String>()
    return (toolIds + skillIds.flatMap { skillsByID[$0]?.requiredToolIds ?? [] })
      .filter { seen.insert($0).inserted }
  }
}

public struct Attachment: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var size: Int
  public var kind: String
  public var format: String
  public var contentType: String
  public var createdAt: String?
}

public typealias BotDocument = Attachment

public struct ChatMessage: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var role: String
  public var authorType: String?
  public var authorId: String?
  public var authorName: String?
  public var authorColor: String?
  public var isMine: Bool?
  public var source: String?
  public var scheduleName: String?
  public var text: String
  public var activity: [String]?
  public var attachments: [Attachment]?
  public var approvalTools: [String]?
  public var roundId: String?
  public var roundPosition: Int?
  public var roundSize: Int?
  public var roundRole: String?
  public var createdAt: String
  public var startedAt: String?
  public var completedAt: String?
  public var activityUpdatedAt: String?
  public var status: String
  public var allowedActions: [String]?
  public var configurationChanged: Bool? = nil

  public var isUser: Bool { role == "user" }
  public var isActive: Bool { ["waiting", "pending", "running"].contains(status) }
  public var needsAction: Bool { ["needs_input", "awaiting_approval"].contains(status) }
}

public struct MessagePage: Codable, Sendable {
  public var messages: [ChatMessage]
  public var nextToken: String?
}

public struct GroupMember: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var role: String
  public var allowedActions: [String]?
}

public struct GroupBot: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var ownerId: String
  public var name: String
  public var tagline: String
  public var color: String
  public var systemRole: String?
}

public struct GroupDecision: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var text: String
  public var sourceMessageId: String
  public var sourceAuthorName: String
  public var createdById: String
  public var createdByName: String
  public var createdAt: String
  public var allowedActions: [String]?
}

public struct BotGroup: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var memory: String
  public var memoryUpdatedAt: String?
  public var memoryUpdatedByName: String?
  public var ownerId: String
  public var currentUserId: String
  public var isOwner: Bool
  public var allowedActions: [String]?
  public var members: [GroupMember]
  public var bots: [GroupBot]
  public var decisions: [GroupDecision]
  public var createdAt: String
  public var updatedAt: String
  public var lastMessage: String
  public var lastMessageAt: String
  public var processing: Bool?
  public var processingBotName: String?
}

public enum ConversationListItem: Identifiable, Hashable, Sendable {
  case bot(Bot)
  case group(BotGroup)

  public var id: ConversationSelection { selection }

  public var selection: ConversationSelection {
    switch self {
    case .bot(let bot): ConversationSelection(kind: .bot, id: bot.id)
    case .group(let group): ConversationSelection(kind: .group, id: group.id)
    }
  }

  public var name: String {
    switch self {
    case .bot(let bot): bot.name
    case .group(let group): group.name
    }
  }

  public var lastMessage: String {
    switch self {
    case .bot(let bot): bot.lastMessage
    case .group(let group): group.lastMessage
    }
  }

  public var lastMessageAt: String {
    switch self {
    case .bot(let bot): bot.lastMessageAt
    case .group(let group): group.lastMessageAt
    }
  }

  public var processing: Bool {
    switch self {
    case .bot(let bot): bot.processing == true
    case .group(let group): group.processing == true
    }
  }

  public var processingBotName: String? {
    switch self {
    case .bot(let bot): bot.name
    case .group(let group): group.processingBotName
    }
  }

  public static func recentFirst(bots: [Bot], groups: [BotGroup]) -> [ConversationListItem] {
    (bots.map(ConversationListItem.bot) + groups.map(ConversationListItem.group)).sorted {
      let left = $0.lastMessageAt.froggyDate ?? .distantPast
      let right = $1.lastMessageAt.froggyDate ?? .distantPast
      if left != right { return left > right }
      return $0.name.localizedStandardCompare($1.name) == .orderedAscending
    }
  }
}

public struct GroupDraft: Codable, Equatable, Sendable {
  public var name = ""
  public var memory = ""
  public var botIds: [String] = []
  public init() {}
  public init(group: BotGroup) {
    name = group.name
    memory = group.memory
    botIds = group.bots.map(\.id)
  }
}

public struct ScheduledTask: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var botId: String
  public var groupId: String?
  public var name: String
  public var prompt: String
  public var frequency: String
  public var dayOfWeek: String?
  public var dayOfMonth: Int?
  public var time: String
  public var timezone: String
  public var enabled: Bool
  public var createdAt: String
  public var updatedAt: String
  public var lastRunAt: String?
  public var lastStatus: String?
}

public struct ScheduledTaskDraft: Codable, Equatable, Sendable {
  public var name = ""
  public var prompt = ""
  public var frequency = "daily"
  public var dayOfWeek: String?
  public var dayOfMonth: Int?
  public var time = "09:00"
  public var timezone = TimeZone.current.identifier
  public var enabled = true
  public init() {}
  public init(task: ScheduledTask) {
    name = task.name
    prompt = task.prompt
    frequency = task.frequency
    dayOfWeek = task.dayOfWeek
    dayOfMonth = task.dayOfMonth
    time = task.time
    timezone = task.timezone
    enabled = task.enabled
  }
}

public struct ScheduleRun: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var botId: String
  public var groupId: String?
  public var scheduleId: String
  public var scheduleName: String
  public var prompt: String
  public var status: String
  public var createdAt: String
  public var completedAt: String?
  public var output: String?
  public var activity: [String]?
  public var approvalTools: [String]?
  public var attachments: [Attachment]?
}

public struct MemoryRecord: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var kind: String
  public var content: String
  public var createdAt: String
  public var scope: String
  public var source: String
  public var botId: String?
  public var botName: String?
}

public struct MemorySnapshot: Codable, Sendable {
  public var records: [MemoryRecord]
  public var rawConversationRetentionDays: Int
}

public struct SharedLink: Codable, Identifiable, Hashable, Sendable {
  public var token: String
  public var kind: String
  public var title: String
  public var url: String
  public var createdAt: String?
  public var expiresAt: Int
  public var id: String { token }
}

public struct InvitePreview: Codable, Sendable {
  public var kind: String
  public var token: String?
  public var title: String
  public var description: String
  public var inviterName: String?
  public var peopleCount: Int?
  public var bots: [GroupBotPreview]
  public var expiresAt: Int
}

public struct GroupBotPreview: Codable, Hashable, Sendable {
  public var name: String
  public var tagline: String
  public var color: String
}

public struct Capability: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var description: String
  public var provider: String?
  public var risk: String?
  public var category: String?
  public var author: String?
  public var tags: [String]?
  public var featured: Bool?
  public var actions: [String]?
  public var source: String?
  public var editable: Bool?
  public var connectedAccount: String?
  public var repositories: [ConnectedRepository]?
  public var connectionStatus: String?
  public var relationship: String?
  public var updatedAt: String?
}

public struct ConnectedRepository: Codable, Identifiable, Hashable, Sendable {
  public var id: Int
  public var name: String
}

public struct ConnectionProvider: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var description: String
  public var category: String
  public var iconText: String
  public var permissionsSummary: String
  public var privacyTitle: String
  public var privacyDescription: String
  public var connectLabel: String
  public var reconnectLabel: String
  public var familyId: String?
  public var familyName: String?
  public var familyDescription: String?
  public var familyIconText: String?
  public var familyLogoProviderId: String?
  public var familyIncludedSummary: String?
  public var familyIncludedToolIds: [String]?
  public var serviceName: String?

  private enum CodingKeys: String, CodingKey {
    case id, name, description, category, iconText, permissionsSummary
    case privacyTitle, privacyDescription, connectLabel, reconnectLabel
    case familyId, familyName, familyDescription, familyIconText, familyLogoProviderId
    case familyIncludedSummary, familyIncludedToolIds, serviceName
  }

  public init(
    id: String, name: String, description: String, category: String, iconText: String,
    permissionsSummary: String, privacyTitle: String, privacyDescription: String,
    connectLabel: String = "Connect account", reconnectLabel: String = "Reconnect account",
    familyId: String? = nil, familyName: String? = nil, familyDescription: String? = nil,
    familyIconText: String? = nil, familyLogoProviderId: String? = nil,
    familyIncludedSummary: String? = nil, familyIncludedToolIds: [String]? = nil,
    serviceName: String? = nil
  ) {
    self.id = id
    self.name = name
    self.description = description
    self.category = category
    self.iconText = iconText
    self.permissionsSummary = permissionsSummary
    self.privacyTitle = privacyTitle
    self.privacyDescription = privacyDescription
    self.connectLabel = connectLabel
    self.reconnectLabel = reconnectLabel
    self.familyId = familyId
    self.familyName = familyName
    self.familyDescription = familyDescription
    self.familyIconText = familyIconText
    self.familyLogoProviderId = familyLogoProviderId
    self.familyIncludedSummary = familyIncludedSummary
    self.familyIncludedToolIds = familyIncludedToolIds
    self.serviceName = serviceName
  }

  public init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    id = try container.decode(String.self, forKey: .id)
    name = try container.decode(String.self, forKey: .name)
    description = try container.decode(String.self, forKey: .description)
    category = try container.decode(String.self, forKey: .category)
    iconText = try container.decode(String.self, forKey: .iconText)
    permissionsSummary = try container.decode(String.self, forKey: .permissionsSummary)
    privacyTitle = try container.decode(String.self, forKey: .privacyTitle)
    privacyDescription = try container.decode(String.self, forKey: .privacyDescription)

    let usesInstallationLanguage = id == "github"
    connectLabel =
      try container.decodeIfPresent(String.self, forKey: .connectLabel)
      ?? (usesInstallationLanguage ? "Install app" : "Connect account")
    reconnectLabel =
      try container.decodeIfPresent(String.self, forKey: .reconnectLabel)
      ?? (usesInstallationLanguage ? "Update installation" : "Reconnect account")
    familyId = try container.decodeIfPresent(String.self, forKey: .familyId)
    familyName = try container.decodeIfPresent(String.self, forKey: .familyName)
    familyDescription = try container.decodeIfPresent(String.self, forKey: .familyDescription)
    familyIconText = try container.decodeIfPresent(String.self, forKey: .familyIconText)
    familyLogoProviderId = try container.decodeIfPresent(
      String.self, forKey: .familyLogoProviderId)
    familyIncludedSummary = try container.decodeIfPresent(
      String.self, forKey: .familyIncludedSummary)
    familyIncludedToolIds = try container.decodeIfPresent(
      [String].self, forKey: .familyIncludedToolIds)
    serviceName = try container.decodeIfPresent(String.self, forKey: .serviceName)
  }
}

struct ConnectionProviderFamily: Identifiable, Hashable, Sendable {
  let id: String
  let name: String
  let description: String
  let iconText: String
  let logoProviderId: String
  let includedSummary: String?
  let includedToolIDs: [String]
  let grouped: Bool
  var providers: [ConnectionProvider]
}

func connectionProviderFamilies(_ providers: [ConnectionProvider]) -> [ConnectionProviderFamily] {
  var families: [ConnectionProviderFamily] = []
  var positions: [String: Int] = [:]
  for provider in providers {
    let familyID = provider.familyId ?? provider.id
    if let position = positions[familyID] {
      families[position].providers.append(provider)
      continue
    }
    positions[familyID] = families.count
    families.append(
      ConnectionProviderFamily(
        id: familyID,
        name: provider.familyName ?? provider.name,
        description: provider.familyDescription ?? provider.description,
        iconText: provider.familyIconText ?? provider.iconText,
        logoProviderId: provider.familyLogoProviderId ?? provider.id,
        includedSummary: provider.familyIncludedSummary,
        includedToolIDs: provider.familyIncludedToolIds ?? [],
        grouped: provider.familyId != nil,
        providers: [provider]))
  }
  return families
}

struct ConnectionProviderToolGroup: Identifiable {
  var id: String { family.id }
  let family: ConnectionProviderFamily
  let tools: [Capability]
}

func connectionProviderToolGroups(
  tools: [Capability], providers: [ConnectionProvider]
) -> (groups: [ConnectionProviderToolGroup], ungrouped: [Capability]) {
  var groupedToolIDs = Set<String>()
  let groups: [ConnectionProviderToolGroup] = connectionProviderFamilies(providers).compactMap {
    family -> ConnectionProviderToolGroup? in
    guard family.grouped else { return nil }
    let providerIDs = Set(family.providers.map(\.id))
    let includedToolIDs = Set(family.includedToolIDs)
    let familyTools = tools.filter { tool in
      includedToolIDs.contains(tool.id)
        || tool.provider.map(providerIDs.contains) == true
    }
    groupedToolIDs.formUnion(familyTools.map(\.id))
    return ConnectionProviderToolGroup(family: family, tools: familyTools)
  }
  return (groups, tools.filter { !groupedToolIDs.contains($0.id) })
}

public struct ConnectionAuthorizationCallback: Equatable, Sendable {
  public enum Status: String, Equatable, Sendable {
    case connected
    case error
  }

  public let providerID: String
  public let status: Status

  public init?(url: URL) {
    guard url.scheme?.lowercased() == "froggybot", url.host?.lowercased() == "app",
      let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
      let providerID = components.queryItems?.first(where: { $0.name == "connection" })?.value,
      !providerID.isEmpty,
      let rawStatus = components.queryItems?.first(where: { $0.name == "status" })?.value,
      let status = Status(rawValue: rawStatus)
    else { return nil }
    self.providerID = providerID
    self.status = status
  }
}

public enum PushRegistrationState: Equatable, Sendable {
  case idle
  case registering
  case registered
  case failed(String)
}

public struct Skill: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var description: String
  public var provider: String?
  public var risk: String?
  public var category: String?
  public var author: String?
  public var tags: [String]?
  public var featured: Bool?
  public var actions: [String]?
  public var version: Int
  public var requiredToolIds: [String]
  public var source: String
  public var visibility: String
  public var editable: Bool
  public var relationship: String?
  public var updatedAt: String?
  public var sourceUrl: String?
}

public struct SkillDetail: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var description: String
  public var provider: String?
  public var risk: String?
  public var category: String?
  public var author: String?
  public var tags: [String]?
  public var featured: Bool?
  public var actions: [String]?
  public var version: Int
  public var requiredToolIds: [String]
  public var source: String
  public var visibility: String
  public var editable: Bool
  public var relationship: String?
  public var updatedAt: String?
  public var sourceUrl: String?
  public var instructions: String
}

public struct SkillDraft: Codable, Equatable, Sendable {
  public var name = ""
  public var description = ""
  public var instructions = ""
  public var requiredToolIds: [String] = []
  public var visibility = "private"
  public var sourceUrl: String?
  public init() {}
  public init(skill: SkillDetail) {
    name = skill.name
    description = skill.description
    instructions = skill.instructions
    requiredToolIds = skill.requiredToolIds
    visibility = skill.visibility
    sourceUrl = skill.sourceUrl
  }
  public init(preview: GitHubSkillPreview) {
    name = preview.name
    description = preview.description
    instructions = preview.instructions
    sourceUrl = preview.sourceUrl
  }
}

public struct GitHubSkillEntry: Codable, Identifiable, Hashable, Sendable {
  public var name: String
  public var path: String
  public var blobSha: String
  public var sourceUrl: String
  public var id: String { path }
}

public struct GitHubSkillScan: Codable, Sendable {
  public var repository: String
  public var reference: String
  public var skills: [GitHubSkillEntry]
  public var moreAvailable: Bool
}

public struct GitHubSkillPreview: Codable, Sendable {
  public var name: String
  public var description: String
  public var instructions: String
  public var sourceUrl: String
  public var warnings: [String]
}

public struct AppConstraints: Codable, Equatable, Sendable {
  public var botNameMaxLength: Int
  public var botTaglineMaxLength: Int
  public var botPromptMaxLength: Int
  public var groupNameMaxLength: Int
  public var groupMemoryMaxLength: Int
  public var messageMaxLength: Int
  public var scheduleNameMaxLength: Int
  public var schedulePromptMaxLength: Int
  public var scheduleDayOfMonthMin: Int
  public var scheduleDayOfMonthMax: Int
  public var skillNameMaxLength: Int
  public var skillDescriptionMaxLength: Int
  public var skillInstructionsMaxLength: Int
  public var memoryMaxLength: Int
  public var maxAttachmentsPerMessage: Int
  public var imageMaxBytes: Int
  public var documentMaxBytes: Int
  public var maxPhotoDimension: Int

  /// Matches the limits used by the deployed service before `/bootstrap` began returning them.
  public static let serviceDefaults = AppConstraints(
    botNameMaxLength: 48,
    botTaglineMaxLength: 120,
    botPromptMaxLength: 12_000,
    groupNameMaxLength: 64,
    groupMemoryMaxLength: 4_000,
    messageMaxLength: 8_000,
    scheduleNameMaxLength: 64,
    schedulePromptMaxLength: 8_000,
    scheduleDayOfMonthMin: 1,
    scheduleDayOfMonthMax: 28,
    skillNameMaxLength: 80,
    skillDescriptionMaxLength: 240,
    skillInstructionsMaxLength: 20_000,
    memoryMaxLength: 16_000,
    maxAttachmentsPerMessage: 5,
    imageMaxBytes: 3_750_000,
    documentMaxBytes: 4_500_000,
    maxPhotoDimension: 1_920)
}

public struct Bootstrap: Codable, Sendable {
  public var bots: [Bot]
  public var botTemplates: [BotTemplate]
  public var connectionProviders: [ConnectionProvider]
  public var needsBotOnboarding: Bool
  public var groups: [BotGroup]
  public var tools: [Capability]
  public var retiredToolIds: [String]
  public var skills: [Skill]
  public var constraints: AppConstraints

  public init(
    bots: [Bot],
    botTemplates: [BotTemplate],
    connectionProviders: [ConnectionProvider],
    needsBotOnboarding: Bool,
    groups: [BotGroup],
    tools: [Capability],
    retiredToolIds: [String],
    skills: [Skill],
    constraints: AppConstraints
  ) {
    self.bots = bots
    self.botTemplates = botTemplates
    self.connectionProviders = connectionProviders
    self.needsBotOnboarding = needsBotOnboarding
    self.groups = groups
    self.tools = tools
    self.retiredToolIds = retiredToolIds
    self.skills = skills
    self.constraints = constraints
  }

  private enum CodingKeys: String, CodingKey {
    case bots, botTemplates, connectionProviders, needsBotOnboarding, groups, tools
    case retiredToolIds, skills, constraints
  }

  public init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    bots = try container.decode([Bot].self, forKey: .bots)
    botTemplates = try container.decode([BotTemplate].self, forKey: .botTemplates)
    connectionProviders =
      try container.decodeIfPresent([ConnectionProvider].self, forKey: .connectionProviders) ?? []
    needsBotOnboarding = try container.decode(Bool.self, forKey: .needsBotOnboarding)
    groups = try container.decode([BotGroup].self, forKey: .groups)
    tools = try container.decode([Capability].self, forKey: .tools)
    retiredToolIds = try container.decode([String].self, forKey: .retiredToolIds)
    skills = try container.decode([Skill].self, forKey: .skills)
    constraints =
      try container.decodeIfPresent(AppConstraints.self, forKey: .constraints) ?? .serviceDefaults
  }
}

public struct BrowserState: Codable, Sendable {
  public var botId: String
  public var groupId: String?
  public var status: String
  public var contextLabel: String
  public var hasSavedLogin: Bool
  public var display: String?
  public var viewport: BrowserViewport?
  public var mobileSiteSupported: Bool?
  public var recoveryRequired: Bool?
  public var sessionExpiresAt: String?
  public var liveViewUrl: String?
  public var liveViewExpiresAt: String?
  public var resumedTurnId: String?
}

public struct BrowserViewport: Codable, Sendable {
  public var width: Int
  public var height: Int
}

public struct UploadAsset: Sendable {
  public var url: URL
  public var name: String
  public var size: Int
  public init(url: URL, name: String? = nil, size: Int? = nil) throws {
    self.url = url
    self.name = name ?? url.lastPathComponent
    let values = try url.resourceValues(forKeys: [.fileSizeKey])
    self.size = size ?? values.fileSize ?? 0
  }
}

public enum PhotoUploadError: LocalizedError, Equatable, Sendable {
  case invalidImage
  case encodingFailed
  case exceedsLimit(Int)

  public var errorDescription: String? {
    switch self {
    case .invalidImage: "That photo could not be read."
    case .encodingFailed: "That photo could not be prepared for upload."
    case .exceedsLimit(let bytes):
      "That photo is still larger than the \(ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)) upload limit."
    }
  }
}

public enum PhotoUploadPreparer {
  public static func jpegData(from data: Data, maxDimension: Int, maxBytes: Int) throws -> Data {
    guard maxDimension > 0, maxBytes > 0,
      let source = CGImageSourceCreateWithData(data as CFData, nil)
    else { throw PhotoUploadError.invalidImage }
    return try jpegData(from: source, maxDimension: maxDimension, maxBytes: maxBytes)
  }

  public static func jpegData(from url: URL, maxDimension: Int, maxBytes: Int) throws -> Data {
    guard maxDimension > 0, maxBytes > 0,
      let source = CGImageSourceCreateWithURL(url as CFURL, nil)
    else { throw PhotoUploadError.invalidImage }
    return try jpegData(from: source, maxDimension: maxDimension, maxBytes: maxBytes)
  }

  private static func jpegData(
    from source: CGImageSource, maxDimension: Int, maxBytes: Int
  ) throws -> Data {
    let thumbnailOptions: [CFString: Any] = [
      kCGImageSourceCreateThumbnailFromImageAlways: true,
      kCGImageSourceCreateThumbnailWithTransform: true,
      kCGImageSourceThumbnailMaxPixelSize: maxDimension,
      kCGImageSourceShouldCacheImmediately: true,
    ]
    guard let image = CGImageSourceCreateThumbnailAtIndex(
      source, 0, thumbnailOptions as CFDictionary)
    else { throw PhotoUploadError.invalidImage }

    for quality in stride(from: 0.9, through: 0.3, by: -0.1) {
      let output = NSMutableData()
      guard
        let destination = CGImageDestinationCreateWithData(
          output, UTType.jpeg.identifier as CFString, 1, nil)
      else { throw PhotoUploadError.encodingFailed }
      CGImageDestinationAddImage(
        destination, image,
        [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
      guard CGImageDestinationFinalize(destination) else {
        throw PhotoUploadError.encodingFailed
      }
      let encoded = output as Data
      if encoded.count <= maxBytes { return encoded }
    }
    throw PhotoUploadError.exceedsLimit(maxBytes)
  }
}

extension String {
  public var froggyDate: Date? {
    let value = ISO8601DateFormatter()
    value.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let result = value.date(from: self) { return result }
    value.formatOptions = [.withInternetDateTime]
    return value.date(from: self)
  }
}
