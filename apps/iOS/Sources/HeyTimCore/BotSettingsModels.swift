import Foundation

public struct BotDraft: Codable, Equatable, Sendable {
  public var name = ""
  public var tagline = ""
  // Chief owns Tim yellow. New custom bots start with the service's supported teal.
  public var color = "#58BEAA"
  public var prompt = ""
  public var toolIds: [String] = []
  public var skillIds: [String] = []
  public var actionApprovalMode = "automatic"
  public var modelPreference = "deepseek"
  public var reasoningEffort = "high"
  public var conversationMode = "agent"
  public var forkFromBotId: String? = nil
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
    actionApprovalMode = bot.actionApprovalMode == "ask" ? "ask" : "automatic"
    modelPreference = bot.modelPreference == "glm" ? "glm" : "deepseek"
    let effort = bot.reasoningEffort ?? "high"
    reasoningEffort = ["low", "high", "max"].contains(effort) ? effort : "high"
    conversationMode = bot.conversationMode == "chat" ? "chat" : "agent"
    alwaysAllowedToolIds = bot.alwaysAllowedToolIds ?? []
    githubRepositoryAccess = bot.githubRepositoryAccess ?? [:]
    jiraProjectAccess = bot.jiraProjectAccess ?? [:]
    teamsChannelAccess = bot.teamsChannelAccess ?? [:]
    resourceAccess = bot.resourceAccess ?? [:]
  }
}
