import SwiftUI

struct AccountUsageView: View {
  let usage: BillingUsageSummary
  let plan: String

  var body: some View {
    VStack(alignment: .leading, spacing: 9) {
      Divider()
      Text("Model usage")
        .froggyFont(.subheadline, weight: .semibold)
      Text(periodLabel)
        .froggyFont(.caption)
        .foregroundStyle(.secondary)
      LabeledContent("Recorded cost", value: costLabel)
      LabeledContent("Total tokens", value: usage.totalTokens.formatted())
      LabeledContent("Input", value: usage.inputTokens.formatted())
      LabeledContent("Output", value: usage.outputTokens.formatted())
      if let imageTokens = usage.imageTokens, imageTokens > 0 {
        LabeledContent("Image tokens", value: imageTokens.formatted())
      }
      LabeledContent("Cached input", value: cachedInputLabel)
      if usage.cacheWriteInputTokens > 0 {
        LabeledContent("Cache writes", value: usage.cacheWriteInputTokens.formatted())
      }
      if usage.imageCostIncomplete == true {
        Label("Some image generation charges are unavailable. Recorded cost is partial.",
              systemImage: "info.circle")
          .froggyFont(.footnote)
          .foregroundStyle(.secondary)
      }
      if usage.tokenIncomplete == true {
        Label("Some image token counts are unavailable, so total tokens are partial.",
              systemImage: "info.circle")
          .froggyFont(.footnote)
          .foregroundStyle(.secondary)
      }
      if usage.costIncomplete, usage.imageCostIncomplete != true {
        Label("Some model costs are unavailable, so the recorded cost is partial.",
              systemImage: "info.circle")
          .froggyFont(.footnote)
          .foregroundStyle(.secondary)
      } else if usage.costEstimated {
        Label("Some model costs are estimates.", systemImage: "info.circle")
          .froggyFont(.footnote)
          .foregroundStyle(.secondary)
      }
    }
    .accessibilityIdentifier("settings.plan.usage")
  }

  private var periodLabel: String {
    guard let start = usage.periodStart.froggyDate,
      let end = usage.periodEnd.froggyDate
    else { return "Current usage period" }
    let formatter = DateFormatter()
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.dateStyle = .medium
    formatter.timeStyle = plan == "plus" ? .short : .none
    let lastIncluded = plan == "plus" ? end : end.addingTimeInterval(-1)
    return "\(formatter.string(from: start)) – \(formatter.string(from: lastIncluded)) UTC"
  }

  private var costLabel: String {
    guard let amount = Decimal(string: usage.totalCostUsd) else { return "Unavailable" }
    if amount > 0 && amount < Decimal(string: "0.000001")! { return "<$0.000001" }
    return String(format: "$%.6f", NSDecimalNumber(decimal: amount).doubleValue)
  }

  private var cachedInputLabel: String {
    switch usage.cacheCoverage {
    case "complete": return usage.cacheReadInputTokens.formatted()
    case "partial": return "\(usage.cacheReadInputTokens.formatted()) recorded (partial)"
    default: return "Unavailable"
    }
  }
}
