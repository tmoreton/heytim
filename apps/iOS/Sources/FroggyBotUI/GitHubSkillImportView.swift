import SwiftUI

private struct ImportedSkillDraft: Identifiable, Hashable {
  let id = UUID()
  let preview: GitHubSkillPreview
  static func == (lhs: Self, rhs: Self) -> Bool { lhs.id == rhs.id }
  func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

struct GitHubSkillImportView: View {
  @Bindable var model: AppModel
  @State private var url = ""
  @State private var scan: GitHubSkillScan?
  @State private var preview: GitHubSkillPreview?
  @State private var draftToEdit: ImportedSkillDraft?
  @State private var loading = false
  @State private var previewing = false
  @State private var error: String?

  var body: some View {
    Form {
      Section {
        TextField("https://github.com/owner/skills", text: $url)
          .textContentType(.URL)
          .autocorrectionDisabled()
          #if os(iOS)
            .textInputAutocapitalization(.never)
            .keyboardType(.URL)
          #endif
        Button {
          Task { await findSkills() }
        } label: {
          if loading { ProgressView() } else { Label("Find Skills", systemImage: "magnifyingglass") }
        }
        .disabled(loading || url.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
      } header: {
        Text("GitHub library")
      } footer: {
        Text("Paste a public repository, folder, or direct SKILL.md link.")
      }

      if let error {
        Section { Text(error).foregroundStyle(.red) }
      }

      if let scan {
        Section("Skills in \(scan.repository)") {
          ForEach(scan.skills) { entry in
            Button {
              Task { await loadPreview(entry, in: scan) }
            } label: {
              VStack(alignment: .leading, spacing: 3) {
                Text(entry.name).froggyFont(.headline)
                Text(entry.path).froggyFont(.caption).foregroundStyle(.secondary)
              }
              .frame(maxWidth: .infinity, alignment: .leading)
            }
            .disabled(previewing)
          }
          if scan.moreAvailable {
            Text("More skills are available. Paste a folder or direct SKILL.md link to narrow the list.")
              .foregroundStyle(.secondary)
          }
        }
      }

      if previewing {
        Section { ProgressView("Loading skill…") }
      }

      if let preview {
        Section("Review \(preview.name)") {
          Text(preview.description)
          if let source = URL(string: preview.sourceUrl) {
            Link("View original on GitHub", destination: source)
          }
          DisclosureGroup("Read Instructions") {
            Text(preview.instructions).textSelection(.enabled).padding(.vertical, 6)
          }
          Button("Edit and Save a Copy", systemImage: "square.and.arrow.down") {
            draftToEdit = ImportedSkillDraft(preview: preview)
          }
        }
        Section("Before you save") {
          Text("Only the SKILL.md instructions are copied. Other files and scripts stay in the source repository. Choose any tools yourself in the editor.")
          ForEach(preview.warnings, id: \.self) { warning in
            Label(warning, systemImage: "exclamationmark.triangle")
          }
        }
      }
    }
    .formStyle(.grouped)
    .froggyListSurface()
    .froggyNavigationTitle("Import Skill")
    .toolbarTitleDisplayMode(.inline)
    .navigationDestination(item: $draftToEdit) { destination in
      SkillEditor(
        model: model, id: nil, showsDismissButton: false,
        initialDraft: SkillDraft(preview: destination.preview))
    }
  }

  private func findSkills() async {
    loading = true
    error = nil
    scan = nil
    preview = nil
    defer { loading = false }
    do {
      let found = try await model.requireAPI().scanGitHubSkills(url.trimmingCharacters(in: .whitespacesAndNewlines))
      scan = found
      if found.skills.count == 1, let first = found.skills.first {
        await loadPreview(first, in: found)
      }
    } catch {
      self.error = error.localizedDescription
    }
  }

  private func loadPreview(_ entry: GitHubSkillEntry, in scan: GitHubSkillScan) async {
    previewing = true
    preview = nil
    error = nil
    defer { previewing = false }
    do {
      preview = try await model.requireAPI().previewGitHubSkill(
        repository: scan.repository, reference: scan.reference, entry: entry)
    } catch {
      self.error = error.localizedDescription
    }
  }
}
