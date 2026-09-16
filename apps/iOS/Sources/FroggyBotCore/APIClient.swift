import Foundation

public struct AppConfiguration: Codable, Sendable {
  public struct Auth: Codable, Sendable {
    public var userPoolId: String
    public var awsRegion: String
    public var userPoolClientId: String
    enum CodingKeys: String, CodingKey {
      case userPoolId = "user_pool_id"
      case awsRegion = "aws_region"
      case userPoolClientId = "user_pool_client_id"
    }
  }
  public struct Custom: Codable, Sendable {
    public var apiUrl: String
    public var shareBaseUrl: String
  }
  public var auth: Auth
  public var custom: Custom

  public static func load(bundle: Bundle = .main) throws -> AppConfiguration {
    guard let url = bundle.url(forResource: "amplify_outputs", withExtension: "json") else {
      throw APIError.configuration("amplify_outputs.json is missing from the app bundle.")
    }
    return try JSONDecoder().decode(AppConfiguration.self, from: Data(contentsOf: url))
  }
}

public enum APIError: LocalizedError, Equatable, Sendable {
  case configuration(String)
  case invalidResponse
  case requestFailed(status: Int, code: String, message: String)
  case sessionExpired
  case uploadFailed(Int)
  case downloadFailed(Int)

  public var errorDescription: String? {
    switch self {
    case .configuration(let message): message
    case .invalidResponse: "The service returned an invalid response."
    case .requestFailed(_, _, let message): message
    case .sessionExpired: "Your session expired. Please sign in again."
    case .uploadFailed(let status): "The file upload failed (\(status))."
    case .downloadFailed(let status): "The file download failed (\(status))."
    }
  }
}

public struct EmptyResponse: Codable, Sendable { public init() {} }

private struct APIErrorBody: Decodable {
  var code: String?
  var message: String?
}
private struct ArrayEnvelope<Value: Codable & Sendable>: Codable, Sendable {
  let values: [Value]
  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: DynamicKey.self)
    guard let key = container.allKeys.first else {
      throw DecodingError.dataCorrupted(
        .init(codingPath: decoder.codingPath, debugDescription: "Expected an array envelope."))
    }
    values = try container.decode([Value].self, forKey: key)
  }
  func encode(to encoder: Encoder) throws { _ = encoder }
}
private struct DynamicKey: CodingKey {
  var stringValue: String
  var intValue: Int?
  init?(stringValue: String) { self.stringValue = stringValue }
  init?(intValue: Int) {
    self.stringValue = String(intValue)
    self.intValue = intValue
  }
}
private struct StringEnvelope: Codable { var url: String }
private struct AuthorizationEnvelope: Codable { var authorizationUrl: String }
private struct UploadTicket: Codable {
  struct Upload: Codable {
    var url: String
    var fields: [String: String]
  }
  var file: Attachment
  var upload: Upload
}

public final class FrogBotAPI: Sendable {
  public typealias TokenProvider = @Sendable () async throws -> String?
  public typealias SessionExpiredHandler = @Sendable (_ rejectedToken: String) async -> Void
  private let baseURL: URL
  private let tokenProvider: TokenProvider
  private let sessionExpiredHandler: SessionExpiredHandler?
  private let session: URLSession

  public init(
    baseURL: URL, session: URLSession = .shared,
    onSessionExpired: SessionExpiredHandler? = nil,
    tokenProvider: @escaping TokenProvider
  ) {
    self.baseURL = baseURL
    self.session = session
    self.tokenProvider = tokenProvider
    sessionExpiredHandler = onSessionExpired
  }

  public convenience init(
    configuration: AppConfiguration, onSessionExpired: SessionExpiredHandler? = nil,
    tokenProvider: @escaping TokenProvider
  ) throws
  {
    guard let url = URL(string: configuration.custom.apiUrl) else {
      throw APIError.configuration("The API URL is invalid.")
    }
    self.init(
      baseURL: url, onSessionExpired: onSessionExpired, tokenProvider: tokenProvider)
  }

  public func request<Response: Decodable & Sendable, Body: Encodable & Sendable>(
    _ id: APIRouteID,
    parameters: [String: String] = [:],
    queryItems: [URLQueryItem] = [],
    body: Body?,
    response: Response.Type = Response.self
  ) async throws -> Response {
    let route = try GeneratedAPIContract.route(id)
    let path = try route.path(parameters: parameters, queryItems: queryItems)
    guard let url = URL(string: path, relativeTo: baseURL)?.absoluteURL else {
      throw APIError.configuration("A request URL could not be created.")
    }
    var value = URLRequest(url: url, timeoutInterval: 30)
    value.httpMethod = route.method.rawValue
    value.setValue("application/json", forHTTPHeaderField: "Accept")
    var bearerToken: String?
    if route.access == .authenticated {
      guard let token = try await tokenProvider(), !token.isEmpty else {
        throw APIError.sessionExpired
      }
      bearerToken = token
      value.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }
    if let body {
      value.httpBody = try JSONEncoder().encode(body)
      value.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }
    let (data, rawResponse) = try await session.data(for: value)
    guard let http = rawResponse as? HTTPURLResponse else { throw APIError.invalidResponse }
    if http.statusCode == 401, let bearerToken {
      await sessionExpiredHandler?(bearerToken)
      throw APIError.sessionExpired
    }
    guard (200..<300).contains(http.statusCode) else {
      let error = try? JSONDecoder().decode(APIErrorBody.self, from: data)
      throw APIError.requestFailed(
        status: http.statusCode,
        code: error?.code ?? "request_failed",
        message: error?.message ?? "The request failed (\(http.statusCode))."
      )
    }
    if Response.self == EmptyResponse.self, data.isEmpty || data == Data("{}".utf8) {
      return EmptyResponse() as! Response
    }
    do { return try JSONDecoder().decode(Response.self, from: data) } catch {
      #if DEBUG
        fputs("FroggyBot decode failure for \(id.rawValue): \(error)\n", stderr)
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
          fputs("FroggyBot response keys for \(id.rawValue): \(object.keys.sorted())\n", stderr)
        }
      #endif
      throw APIError.invalidResponse
    }
  }

  public func request<Response: Decodable & Sendable>(
    _ id: APIRouteID,
    parameters: [String: String] = [:],
    queryItems: [URLQueryItem] = [],
    response: Response.Type = Response.self
  ) async throws -> Response {
    try await request(
      id, parameters: parameters, queryItems: queryItems, body: Optional<String>.none,
      response: response)
  }

  public func bootstrap() async throws -> Bootstrap { try await request(.bootstrap) }
  public func installBotTemplate(_ id: String) async throws -> Bot {
    try await request(.botTemplateInstall, parameters: ["templateId": id], body: EmptyResponse())
  }
  public func saveBot(_ draft: BotDraft, id: String? = nil) async throws -> Bot {
    try await request(
      id == nil ? .botCreate : .botUpdate, parameters: ["botId": id ?? ""], body: draft)
  }
  public func deleteBot(_ id: String) async throws {
    let _: EmptyResponse = try await request(.botDelete, parameters: ["botId": id])
  }
  public func clearBot(_ id: String, forgetMemory: Bool = false) async throws {
    let _: EmptyResponse = try await request(
      .botMessagesClear, parameters: ["botId": id], body: ["forgetMemory": forgetMemory])
  }
  public func botDocuments(_ id: String) async throws -> [BotDocument] {
    let envelope: ArrayEnvelope<BotDocument> = try await request(
      .botDocuments, parameters: ["botId": id])
    return envelope.values
  }
  public func messages(bot id: String, cursor: String? = nil) async throws -> MessagePage {
    try await request(
      .botMessagesList, parameters: ["botId": id],
      queryItems: cursor.map { [.init(name: "cursor", value: $0)] } ?? [])
  }
  public func messages(group id: String, cursor: String? = nil) async throws -> MessagePage {
    try await request(
      .groupMessagesList, parameters: ["groupId": id],
      queryItems: cursor.map { [.init(name: "cursor", value: $0)] } ?? [])
  }
  public func sendMessage(bot id: String, text: String, attachments: [String] = []) async throws {
    let _: EmptyResponse = try await request(
      .botMessageSend, parameters: ["botId": id],
      body: SendMessageBody(text: text, attachmentIds: attachments, replyBotId: nil))
  }
  public func sendMessage(
    group id: String, text: String, replyBotId: String? = nil, attachments: [String] = []
  ) async throws {
    let _: EmptyResponse = try await request(
      .groupMessageSend, parameters: ["groupId": id],
      body: SendMessageBody(text: text, attachmentIds: attachments, replyBotId: replyBotId))
  }
  public func cancel(botId: String, turnId: String) async throws {
    let _: EmptyResponse = try await request(
      .botMessageCancel, parameters: ["botId": botId, "turnId": turnId])
  }
  public func approve(botId: String, turnId: String, always: Bool) async throws {
    let _: EmptyResponse = try await request(
      .botMessageApprove, parameters: ["botId": botId, "turnId": turnId], body: ["always": always])
  }

  public func saveGroup(_ draft: GroupDraft, id: String? = nil) async throws -> BotGroup {
    try await request(
      id == nil ? .groupCreate : .groupUpdate, parameters: ["groupId": id ?? ""], body: draft)
  }
  public func deleteGroup(_ id: String) async throws {
    let _: EmptyResponse = try await request(.groupDelete, parameters: ["groupId": id])
  }
  public func joinGroup(token: String) async throws -> BotGroup {
    try await request(.groupInviteJoin, parameters: ["token": token], body: EmptyResponse())
  }
  public func removeMember(groupId: String, memberId: String) async throws {
    let _: EmptyResponse = try await request(
      .groupMemberDelete, parameters: ["groupId": groupId, "memberId": memberId])
  }
  public func saveDecision(groupId: String, messageId: String) async throws -> GroupDecision {
    try await request(
      .groupDecisionCreate, parameters: ["groupId": groupId], body: ["messageId": messageId])
  }
  public func deleteDecision(groupId: String, decisionId: String) async throws {
    let _: EmptyResponse = try await request(
      .groupDecisionDelete, parameters: ["groupId": groupId, "decisionId": decisionId])
  }

  public func schedules(for selection: ConversationSelection) async throws -> [ScheduledTask] {
    let id: APIRouteID = selection.kind == .bot ? .botSchedulesList : .groupSchedulesList
    let key = selection.kind == .bot ? "botId" : "groupId"
    let envelope: ArrayEnvelope<ScheduledTask> = try await request(
      id, parameters: [key: selection.id])
    return envelope.values
  }
  public func saveSchedule(
    _ draft: ScheduledTaskDraft, selection: ConversationSelection, id: String? = nil
  ) async throws -> ScheduledTask {
    let route: APIRouteID
    if selection.kind == .bot {
      route = id == nil ? .botScheduleCreate : .botScheduleUpdate
    } else {
      route = id == nil ? .groupScheduleCreate : .groupScheduleUpdate
    }
    return try await request(
      route, parameters: scheduleParameters(selection, scheduleId: id), body: draft)
  }
  public func deleteSchedule(_ id: String, selection: ConversationSelection) async throws {
    let route: APIRouteID = selection.kind == .bot ? .botScheduleDelete : .groupScheduleDelete
    let _: EmptyResponse = try await request(
      route, parameters: scheduleParameters(selection, scheduleId: id))
  }
  public func runSchedule(_ id: String, selection: ConversationSelection) async throws {
    let route: APIRouteID = selection.kind == .bot ? .botScheduleRun : .groupScheduleRun
    let _: EmptyResponse = try await request(
      route, parameters: scheduleParameters(selection, scheduleId: id), body: EmptyResponse())
  }
  public func scheduleRuns(for selection: ConversationSelection) async throws -> [ScheduleRun] {
    let route: APIRouteID = selection.kind == .bot ? .botScheduleRuns : .groupScheduleRuns
    let key = selection.kind == .bot ? "botId" : "groupId"
    let envelope: ArrayEnvelope<ScheduleRun> = try await request(
      route, parameters: [key: selection.id])
    return envelope.values
  }

  public func memories(botId: String? = nil, groupId: String? = nil) async throws -> MemorySnapshot {
    if let botId {
      return try await request(.botMemoryList, parameters: ["botId": botId])
    }
    if let groupId {
      return try await request(.groupMemoryList, parameters: ["groupId": groupId])
    }
    return try await request(.memoryList)
  }
  public func createMemory(
    kind: String = "fact", content: String, botId: String? = nil, groupId: String? = nil)
    async throws -> MemoryRecord
  {
    if let botId {
      return try await request(
        .botMemoryCreate, parameters: ["botId": botId], body: ["content": content])
    }
    if let groupId {
      return try await request(
        .groupMemoryCreate, parameters: ["groupId": groupId], body: ["content": content])
    }
    return try await request(.memoryCreate, body: ["kind": kind, "content": content])
  }
  public func updateMemory(
    id: String, content: String, botId: String? = nil, groupId: String? = nil) async throws
    -> MemoryRecord
  {
    if let botId {
      return try await request(
        .botMemoryUpdate,
        parameters: ["botId": botId, "memoryRecordId": id], body: ["content": content])
    }
    let route: APIRouteID = groupId == nil ? .memoryUpdate : .groupMemoryUpdate
    return try await request(
      route, parameters: ["groupId": groupId ?? "", "memoryRecordId": id],
      body: ["content": content])
  }
  public func deleteMemory(id: String, botId: String? = nil, groupId: String? = nil) async throws {
    if let botId {
      let _: EmptyResponse = try await request(
        .botMemoryDelete, parameters: ["botId": botId, "memoryRecordId": id])
      return
    }
    let route: APIRouteID = groupId == nil ? .memoryDelete : .groupMemoryDelete
    let _: EmptyResponse = try await request(
      route, parameters: ["groupId": groupId ?? "", "memoryRecordId": id])
  }
  public func exportMemory() async throws -> URL {
    let value: StringEnvelope = try await request(.memoryExport, body: EmptyResponse())
    guard let url = URL(string: value.url) else { throw APIError.invalidResponse }
    return url
  }

  public func downloadMemoryExport() async throws -> Data {
    let url = try await exportMemory()
    let (data, rawResponse) = try await session.data(from: url)
    guard let response = rawResponse as? HTTPURLResponse else { throw APIError.invalidResponse }
    guard (200..<300).contains(response.statusCode) else {
      throw APIError.downloadFailed(response.statusCode)
    }
    guard (try? JSONSerialization.jsonObject(with: data)) != nil else {
      throw APIError.invalidResponse
    }
    return data
  }

  public func shares() async throws -> [SharedLink] {
    let envelope: ArrayEnvelope<SharedLink> = try await request(.sharesList)
    return envelope.values
  }
  public func share(botId: String, scope: String) async throws -> URL {
    let value: StringEnvelope = try await request(
      .shareCreate, body: ["botId": botId, "scope": scope])
    guard let url = URL(string: value.url) else { throw APIError.invalidResponse }
    return url
  }
  public func shareGroup(_ id: String) async throws -> URL {
    let value: StringEnvelope = try await request(
      .groupInviteCreate, parameters: ["groupId": id], body: EmptyResponse())
    guard let url = URL(string: value.url) else { throw APIError.invalidResponse }
    return url
  }
  public func revokeShare(_ token: String) async throws {
    let _: EmptyResponse = try await request(.shareDelete, parameters: ["token": token])
  }
  public func invitePreview(kind: String, token: String) async throws -> InvitePreview {
    try await request(.publicInvite, parameters: ["kind": kind, "token": token])
  }
  public func importShare(_ token: String) async throws -> Bot {
    try await request(.shareImport, parameters: ["token": token], body: EmptyResponse())
  }

  public func skill(_ id: String) async throws -> SkillDetail {
    try await request(.skillGet, parameters: ["skillId": id])
  }
  public func saveSkill(_ draft: SkillDraft, id: String? = nil) async throws -> SkillDetail {
    try await request(
      id == nil ? .skillCreate : .skillUpdate, parameters: ["skillId": id ?? ""], body: draft)
  }
  public func shareSkill(_ id: String) async throws -> URL {
    let value: StringEnvelope = try await request(
      .skillShare, parameters: ["skillId": id], body: EmptyResponse())
    guard let url = URL(string: value.url) else { throw APIError.invalidResponse }
    return url
  }
  public func importSkill(_ token: String) async throws -> SkillDetail {
    try await request(.skillShareImport, parameters: ["token": token], body: EmptyResponse())
  }

  public func beginConnection(providerId: String, returnURL: URL) async throws -> URL {
    let value: AuthorizationEnvelope = try await request(
      .connectionAuthorize, parameters: ["providerId": providerId],
      body: ["returnUrl": returnURL.absoluteString])
    guard let url = URL(string: value.authorizationUrl) else { throw APIError.invalidResponse }
    return url
  }
  public func connections() async throws -> [Capability] {
    let envelope: ArrayEnvelope<Capability> = try await request(.connectionsList)
    return envelope.values
  }
  public func deleteConnection(_ id: String) async throws {
    let _: EmptyResponse = try await request(.connectionDelete, parameters: ["connectionId": id])
  }

  public func browserState(botId: String, groupId: String? = nil) async throws -> BrowserState {
    try await request(
      .browserStatus, parameters: ["botId": botId],
      queryItems: groupId.map { [.init(name: "groupId", value: $0)] } ?? [])
  }
  public func openBrowser(
    botId: String, groupId: String? = nil, url: URL? = nil, display: String = "desktop"
  ) async throws -> BrowserState {
    try await request(
      .browserOpen, parameters: ["botId": botId],
      body: BrowserBody(groupId: groupId, url: url?.absoluteString, display: display))
  }
  public func resumeBrowser(botId: String, groupId: String? = nil) async throws -> BrowserState {
    try await request(
      .browserResume, parameters: ["botId": botId],
      body: BrowserBody(groupId: groupId, url: nil, display: nil))
  }
  public func closeBrowser(botId: String, groupId: String? = nil) async throws {
    let _: EmptyResponse = try await request(
      .browserClose, parameters: ["botId": botId],
      body: BrowserBody(groupId: groupId, url: nil, display: nil))
  }
  public func forgetBrowserLogin(botId: String) async throws {
    let _: EmptyResponse = try await request(.browserProfileDelete, parameters: ["botId": botId])
  }

  public func registerAPNsToken(_ token: Data, platform: String) async throws {
    let value = token.map { String(format: "%02x", $0) }.joined()
    #if DEBUG
      let environment = "sandbox"
    #else
      let environment = "production"
    #endif
    let _: EmptyResponse = try await request(
      .pushTokenPut,
      body: PushRegistration(
        provider: "apns", token: value, platform: platform, environment: environment))
  }
  public func unregisterAPNsToken(_ token: Data) async throws {
    let value = token.map { String(format: "%02x", $0) }.joined()
    let _: EmptyResponse = try await request(
      .pushTokenDelete,
      body: PushRegistration(provider: "apns", token: value, platform: nil, environment: nil))
  }
  public func deleteAccount() async throws {
    let _: EmptyResponse = try await request(.accountDelete)
  }

  public func upload(_ asset: UploadAsset) async throws -> Attachment {
    let ticket: UploadTicket = try await request(
      .uploadCreate, body: UploadRequest(filename: asset.name, size: asset.size))
    let boundary = "FroggyBot-\(UUID().uuidString)"
    var data = Data()
    for (key, value) in ticket.upload.fields.sorted(by: { $0.key < $1.key }) {
      data.appendMultipart(
        "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(key)\"\r\n\r\n\(value)\r\n")
    }
    data.appendMultipart(
      "--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(asset.name)\"\r\nContent-Type: \(ticket.file.contentType)\r\n\r\n"
    )
    data.append(try Data(contentsOf: asset.url, options: .mappedIfSafe))
    data.appendMultipart("\r\n--\(boundary)--\r\n")
    guard let uploadURL = URL(string: ticket.upload.url) else { throw APIError.invalidResponse }
    var request = URLRequest(url: uploadURL, timeoutInterval: 120)
    request.httpMethod = "POST"
    request.httpBody = data
    request.setValue(
      "multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
    let (_, response) = try await session.data(for: request)
    guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
    guard (200..<300).contains(http.statusCode) else {
      throw APIError.uploadFailed(http.statusCode)
    }
    return try await self.request(
      .uploadComplete, parameters: ["fileId": ticket.file.id], body: EmptyResponse())
  }
  public func downloadURL(fileId: String, groupId: String? = nil) async throws -> URL {
    let route: APIRouteID = groupId == nil ? .fileDownload : .groupFileDownload
    let value: StringEnvelope = try await request(
      route, parameters: ["groupId": groupId ?? "", "fileId": fileId])
    guard let url = URL(string: value.url) else { throw APIError.invalidResponse }
    return url
  }

  public func downloadFile(fileId: String, name: String, groupId: String? = nil) async throws
    -> URL
  {
    let source = try await downloadURL(fileId: fileId, groupId: groupId)
    let (temporaryURL, response) = try await session.download(from: source)
    guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
    guard (200..<300).contains(http.statusCode) else {
      throw APIError.downloadFailed(http.statusCode)
    }

    let folder = FileManager.default.temporaryDirectory
      .appendingPathComponent("FroggyBotPreviews", isDirectory: true)
      .appendingPathComponent(UUID().uuidString, isDirectory: true)
    try FileManager.default.createDirectory(
      at: folder, withIntermediateDirectories: true, attributes: nil)
    let candidate = URL(fileURLWithPath: name).lastPathComponent
      .trimmingCharacters(in: .whitespacesAndNewlines)
    let filename = candidate.isEmpty ? "Preview" : candidate
    let destination = folder.appendingPathComponent(filename, isDirectory: false)
    do {
      try FileManager.default.moveItem(at: temporaryURL, to: destination)
    } catch {
      try? FileManager.default.removeItem(at: folder)
      throw error
    }
    return destination
  }

  public static func removeDownloadedPreview(at url: URL?) {
    guard let url else { return }
    let previewsRoot = FileManager.default.temporaryDirectory
      .appendingPathComponent("FroggyBotPreviews", isDirectory: true)
      .standardizedFileURL
    let folder = url.deletingLastPathComponent().standardizedFileURL
    guard folder.deletingLastPathComponent() == previewsRoot else { return }
    try? FileManager.default.removeItem(at: folder)
  }

  private func scheduleParameters(_ selection: ConversationSelection, scheduleId: String?)
    -> [String: String]
  {
    [selection.kind == .bot ? "botId" : "groupId": selection.id, "scheduleId": scheduleId ?? ""]
  }
}

private struct SendMessageBody: Codable {
  var text: String
  var attachmentIds: [String]
  var replyBotId: String?
}
private struct BrowserBody: Codable {
  var groupId: String?
  var url: String?
  var display: String?
}
private struct PushRegistration: Codable {
  var provider: String
  var token: String
  var platform: String?
  var environment: String?
}
private struct UploadRequest: Codable {
  var filename: String
  var size: Int
}

extension Data {
  fileprivate mutating func appendMultipart(_ value: String) { append(Data(value.utf8)) }
}
