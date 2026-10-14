import SwiftUI

struct WorkspaceSettingsSection: View {
  @Bindable var model: AppModel

  var body: some View {
    Section("Workspace") {
      FeatureLink { MemoriesView(model: model, groupId: nil, showsDismissButton: false) } label: {
        SettingsNavigationLabel(
          title: "Memory", detail: "Review facts and preferences shared across your bots.",
          systemImage: "brain.head.profile")
      }
      FeatureLink { SkillsView(model: model, showsDismissButton: false) } label: {
        SettingsNavigationLabel(
          title: "Tools & Skills", detail: "Browse playbooks and available capabilities.",
          systemImage: "wrench.and.screwdriver")
      }
      FeatureLink { ConnectionsView(model: model, showsDismissButton: false) } label: {
        SettingsNavigationLabel(
          title: "Accounts & MCP Servers", detail: "Connect, reconnect, or remove external services.",
          systemImage: "link")
      }
      FeatureLink { WebhooksView(model: model) } label: {
        SettingsNavigationLabel(
          title: "Webhooks", detail: "Receive Pebble voice notes and messages from external sources.",
          systemImage: "waveform.badge.plus")
      }
    }
  }
}
