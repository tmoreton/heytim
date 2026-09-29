import Foundation

public extension AppModel {
  func forkBotConversation(_ bot: Bot) async -> Bool {
    var draft = BotDraft(bot: bot)
    if bot.systemRole == "chief" { draft.color = "#58BEAA" }
    let maximum = max(1, constraints.botNameMaxLength - " branch".count)
    draft.name = String(bot.name.prefix(maximum)) + " branch"
    draft.forkFromBotId = bot.id
    return await saveBot(draft, id: nil)
  }
}
