import SwiftUI

#if os(macOS)
import AppKit
#else
import UIKit
#endif

private struct WebhookCredentialPresentation: Identifiable {
  let id = UUID()
  var value: WebhookCredential
}

struct WebhooksView: View {
  @Bindable var model: AppModel
  @State private var sources: [WebhookSource] = []
  @State private var events: [WebhookEvent] = []
  @State private var isLoading = false
  @State private var isWorking = false
  @State private var error: String?
  @State private var showsCreate = false
  @State private var credential: WebhookCredentialPresentation?
  @State private var pendingCredential: WebhookCredentialPresentation?
  @State private var deleteCandidate: WebhookSource?
  @State private var rotateCandidate: WebhookSource?
  #if os(macOS)
  @Environment(LocalRoutingCoordinator.self) private var router
  #endif

  var body: some View {
    Form {
      #if os(macOS)
      LocalRoutingSettingsSection(router: router)
      #else
      Section {
        Text("Automatic routing runs in Hey Tim on your Mac. Keep the Mac app running with Local Routing enabled.")
      } header: { Text("Local Routing") }
      #endif
      if let error {
        Section {
          Text(error).foregroundStyle(.red)
          Button("Try Again") { Task { await refresh() } }
        }
      }
      Section {
        ForEach(sources) { source in sourceRow(source) }
        Button("Add Webhook", systemImage: "plus") { showsCreate = true }
          .disabled((model.bootstrap?.bots ?? []).isEmpty || isWorking)
          .accessibilityIdentifier("webhooks.add")
      } header: { Text("Sources") } footer: {
        Text("Each source has its own credentials and permitted bots. Disable or remove a source to stop incoming messages.")
      }
      Section {
        if isLoading && events.isEmpty { ProgressView("Loading incoming messages…") }
        else if events.isEmpty { Text("No incoming messages yet.").foregroundStyle(.secondary) }
        ForEach(events) { event in eventRow(event) }
      } header: { Text("Incoming Messages") } footer: {
        Text("Answers appear in the selected bot’s conversation. Enable notifications on your iPhone to receive completed answers there.")
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .froggyNavigationTitle("Webhooks")
    .toolbarTitleDisplayMode(.inline)
    .toolbar { Button("Refresh", systemImage: "arrow.clockwise") { Task { await refresh() } }.disabled(isLoading) }
    .task {
      await refresh()
      while !Task.isCancelled {
        try? await Task.sleep(for: .seconds(10))
        guard !Task.isCancelled else { return }
        await refresh()
      }
    }
    .sheet(isPresented: $showsCreate, onDismiss: {
      credential = pendingCredential
      pendingCredential = nil
    }) {
      NavigationStack {
        WebhookSourceEditor(bots: model.bootstrap?.bots ?? []) { draft in
          let created = try await model.createWebhookSource(draft)
          pendingCredential = WebhookCredentialPresentation(value: created)
          await refresh()
        }
      }
      .frame(minWidth: 360, minHeight: 480)
    }
    .sheet(item: $credential) { presentation in
      NavigationStack { WebhookCredentialView(credential: presentation.value) }
        .frame(minWidth: 360, minHeight: 480)
    }
    .confirmationDialog("Remove this webhook?", isPresented: Binding(
      get: { deleteCandidate != nil }, set: { if !$0 { deleteCandidate = nil } }
    ), titleVisibility: .visible) {
      if let source = deleteCandidate {
        Button("Remove \(source.name)", role: .destructive) {
          Task { await perform { try await model.deleteWebhookSource(source.id) } }
        }
      }
    } message: { Text("The endpoint will stop accepting messages. Existing conversations stay in your history.") }
    .confirmationDialog("Replace this webhook’s credentials?", isPresented: Binding(
      get: { rotateCandidate != nil }, set: { if !$0 { rotateCandidate = nil } }
    ), titleVisibility: .visible) {
      if let source = rotateCandidate {
        Button("Replace Credentials", role: .destructive) {
          Task {
            await perform {
              credential = WebhookCredentialPresentation(value: try await model.rotateWebhookCredential(source.id))
            }
          }
        }
      }
    } message: { Text("Update the sending application with the new credentials. The old credentials stop working immediately.") }
  }

  private func sourceRow(_ source: WebhookSource) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Label(source.name, systemImage: source.kind == "pebble" ? "waveform" : "link")
        Spacer()
        Text(source.enabled ? "Enabled" : "Disabled").foregroundStyle(.secondary).font(.caption)
        Menu {
          Button(source.enabled ? "Disable" : "Enable") {
            Task { await perform { try await model.updateWebhookSource(source, enabled: !source.enabled) } }
          }
          Button("Copy Endpoint") { copyWebhookValue(source.url) }
          Button("Replace Credentials") { rotateCandidate = source }
          Button("Remove", role: .destructive) { deleteCandidate = source }
        } label: { Image(systemName: "ellipsis.circle") }
        .disabled(isWorking)
      }
      Text(source.routingMode == "local" ? "Choose a bot on this Mac" : "Send to the configured bot")
        .font(.caption).foregroundStyle(.secondary)
      Text(source.url).font(.caption.monospaced()).textSelection(.enabled)
    }
    .padding(.vertical, 4)
  }

  private func eventRow(_ event: WebhookEvent) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Text(event.sourceName).font(.headline)
        Spacer()
        Text(event.status.replacingOccurrences(of: "_", with: " ").capitalized)
          .font(.caption).foregroundStyle(.secondary)
      }
      Text(event.text).lineLimit(8).textSelection(.enabled)
      if let reason = event.reviewReason { Text(reason.replacingOccurrences(of: "_", with: " ")).font(.caption).foregroundStyle(.secondary) }
      if let botId = event.botId, let bot = model.bootstrap?.bots.first(where: { $0.id == botId }) {
        Button("Open \(bot.name)", systemImage: "bubble.left") {
          model.sheet = nil
          model.select(.init(kind: .bot, id: botId))
        }
      } else if event.status != "test", event.status != "rejected" {
        Menu("Choose a Bot") {
          ForEach(eligibleBots(for: event)) { bot in
            Button(bot.name) {
              Task { await perform { try await model.routeWebhookEvent(event.id, botId: bot.id) } }
            }
          }
        }
        .disabled(isWorking || eligibleBots(for: event).isEmpty)
      }
    }
    .padding(.vertical, 6)
  }

  private func eligibleBots(for event: WebhookEvent) -> [Bot] {
    guard let source = sources.first(where: { $0.id == event.sourceId }) else { return [] }
    return (model.bootstrap?.bots ?? []).filter {
      source.allowedBotIds.isEmpty || source.allowedBotIds.contains($0.id)
    }
  }

  private func refresh() async {
    guard !isLoading else { return }
    isLoading = true
    defer { isLoading = false }
    do {
      async let loadedSources = model.loadWebhookSources()
      async let loadedEvents = model.loadWebhookEvents()
      (sources, events) = try await (loadedSources, loadedEvents)
      error = nil
    } catch { self.error = error.localizedDescription }
  }

  private func perform(_ action: () async throws -> Void) async {
    guard !isWorking else { return }
    isWorking = true
    defer { isWorking = false }
    do { try await action(); await refresh() }
    catch { self.error = error.localizedDescription }
  }
}

private struct WebhookSourceEditor: View {
  let bots: [Bot]
  let save: @MainActor (WebhookSourceDraft) async throws -> Void
  @State private var draft = WebhookSourceDraft()
  @State private var isSaving = false
  @State private var error: String?
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    Form {
      Section("Source") {
        TextField("Name", text: $draft.name)
        Picker("Format", selection: $draft.kind) {
          Text("Pebble Index").tag("pebble")
          Text("JSON Webhook").tag("generic")
        }
        if draft.kind == "generic" {
          TextField("Message field (optional, e.g. event.message.text)", text: Binding(
            get: { draft.textPath ?? "" }, set: { draft.textPath = $0.isEmpty ? nil : $0 }
          ))
        }
        Picker("Routing", selection: $draft.routingMode) {
          Text("Choose on my Mac").tag("local")
          Text("Always use one bot").tag("fixed")
        }
        if draft.routingMode == "fixed" {
          Picker("Bot", selection: Binding(
            get: { draft.fallbackBotId ?? "" }, set: { draft.fallbackBotId = $0.isEmpty ? nil : $0 }
          )) {
            Text("Choose a bot").tag("")
            ForEach(bots.filter { draft.allowedBotIds.contains($0.id) }) { bot in Text(bot.name).tag(bot.id) }
          }
        }
      }
      Section {
        ForEach(bots) { bot in
          Toggle(isOn: Binding(
            get: { draft.allowedBotIds.contains(bot.id) },
            set: { included in
              if included { draft.allowedBotIds.append(bot.id) }
              else {
                draft.allowedBotIds.removeAll { $0 == bot.id }
                if draft.fallbackBotId == bot.id { draft.fallbackBotId = nil }
              }
            }
          )) {
            VStack(alignment: .leading) {
              Text(bot.name)
              Text(bot.tagline).font(.caption).foregroundStyle(.secondary)
            }
          }
        }
      } header: { Text("Permitted Bots") } footer: {
        Text("The router can choose only these bots. Messages wait while the Mac is unavailable, and uncertain choices can be reviewed here.")
      }
      if let error { Section { Text(error).foregroundStyle(.red) } }
    }
    .formStyle(.grouped)
    .navigationTitle("New Webhook")
    .toolbar {
      ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(isSaving) }
      ToolbarItem(placement: .confirmationAction) {
        Button("Create") {
          isSaving = true
          Task {
            do { try await save(draft); dismiss() }
            catch { self.error = error.localizedDescription }
            isSaving = false
          }
        }
        .disabled(isSaving || draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
          || draft.allowedBotIds.isEmpty || (draft.routingMode == "fixed" && draft.fallbackBotId == nil))
      }
    }
    .onAppear { if draft.allowedBotIds.isEmpty { draft.allowedBotIds = bots.map(\.id) } }
  }
}

private struct WebhookCredentialView: View {
  let credential: WebhookCredential
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    Form {
      Section {
        Text("Save these credentials now. They are shown once. You can replace them later in Webhooks.")
      }
      Section("Endpoint") { valueRow(credential.source.url) }
      Section { valueRow("Bearer \(credential.credential)") } header: {
        Text("Authorization Header")
      } footer: {
        Text("Add an Authorization header with this value in the sending application.")
      }
      Section { valueRow(credential.signingSecret) } header: {
        Text("Signing Secret")
      } footer: {
        Text("Use this shared secret if the sender supports signed webhooks.")
      }
      Section("Setup") {
        if credential.source.kind == "pebble" {
          Text("In the Pebble app, configure the desired Index gesture’s webhook. Paste the endpoint and Authorization header, select transcription delivery, and add the signing secret if your app offers it. Use Webhook Only when available to avoid duplicate native actions.")
        } else {
          Text("POST JSON with text and a stable eventId. Send a unique eventId for each message, and reuse it for retries. Authenticate with the Authorization header.")
          Text("{\"eventId\":\"example-1\",\"text\":\"What should I prioritize today?\"}")
            .font(.caption.monospaced()).textSelection(.enabled)
        }
        Text("Use the sender’s test action first. Connection tests are acknowledged without asking a bot.")
      }
    }
    .formStyle(.grouped)
    .navigationTitle(credential.source.name)
    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
  }

  private func valueRow(_ value: String) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      Text(value).font(.caption.monospaced()).textSelection(.enabled)
      Button("Copy", systemImage: "doc.on.doc") { copyWebhookValue(value) }
    }
  }
}

private func copyWebhookValue(_ value: String) {
  #if os(macOS)
  NSPasteboard.general.clearContents()
  NSPasteboard.general.setString(value, forType: .string)
  #else
  UIPasteboard.general.string = value
  #endif
}

#if os(macOS)
private struct LocalRoutingSettingsSection: View {
  @Bindable var router: LocalRoutingCoordinator
  var body: some View {
    Section {
      Toggle("Route messages on this Mac", isOn: Binding(get: { router.enabled }, set: { router.setEnabled($0) }))
        .disabled(!router.isSupported || router.isPreparing)
        .accessibilityIdentifier("webhooks.local-routing")
      Text(router.activity).font(.callout).foregroundStyle(.secondary)
      if let error = router.lastError { Text(error).foregroundStyle(.red).font(.callout) }
      if router.isPreparing {
        ProgressView()
        Button("Cancel Download", role: .cancel) { router.cancelSetup() }
      } else if !router.modelInstalled {
        Button("Download Routing Model") { router.prepareModel() }.disabled(!router.isSupported)
          .accessibilityIdentifier("webhooks.download-model")
      }
    } header: { Text("Local Routing") } footer: {
      Text("Requires an Apple silicon Mac and approximately 5 GB for the model download. Classification runs on this Mac; your chosen bot answers through Hey Tim’s existing service. Uncertain reasoning choices keep the bot’s saved preference.")
    }
    .task { await router.checkModel() }
  }
}
#endif
