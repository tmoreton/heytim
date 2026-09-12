import Foundation

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
  public var color = "#59B86B"
  public var prompt = ""
  public var toolIds: [String] = []
  public var skillIds: [String] = []
  public var alwaysAllowedToolIds: [String] = []

  public init() {}
  public init(bot: Bot) {
    name = bot.name
    tagline = bot.tagline
    color = bot.color
    prompt = bot.prompt
    toolIds = bot.toolIds
    skillIds = bot.skillIds
    alwaysAllowedToolIds = bot.alwaysAllowedToolIds ?? []
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
  public var endpoint: String?
  public var authType: String?
  public var headerName: String?
  public var hasCredential: Bool?
  public var connectionStatus: String?
}

public struct ConnectionProvider: Codable, Identifiable, Hashable, Sendable {
  public var id: String
  public var name: String
  public var description: String
  public var category: String
  public var authType: String
  public var uiKind: String
  public var iconText: String
  public var permissionsSummary: String
  public var privacyTitle: String
  public var privacyDescription: String
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
  public var instructions: String
}

public struct SkillDraft: Codable, Equatable, Sendable {
  public var name = ""
  public var description = ""
  public var instructions = ""
  public var requiredToolIds: [String] = []
  public var visibility = "private"
  public init() {}
  public init(skill: SkillDetail) {
    name = skill.name
    description = skill.description
    instructions = skill.instructions
    requiredToolIds = skill.requiredToolIds
    visibility = skill.visibility
  }
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

extension String {
  public var froggyDate: Date? {
    let value = ISO8601DateFormatter()
    value.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let result = value.date(from: self) { return result }
    value.formatOptions = [.withInternetDateTime]
    return value.date(from: self)
  }
}
