import Charts
import Foundation
import SwiftUI

enum InlineMessageElement: Equatable {
  case chart(InlineChart)
  case metrics(InlineMetrics)
  case callout(InlineCallout)
  case steps(InlineSteps)
}

struct InlineChart: Codable, Equatable {
  enum Kind: String, Codable { case bar, line, area }
  enum ValueFormat: String, Codable { case number, currency, percent }

  let type: Kind
  let title: String
  let subtitle: String?
  let format: ValueFormat?
  let currency: String?
  let series: [InlineChartSeries]

  var isValid: Bool {
    title.isInlineElementText(maximum: 120)
      && subtitle.isOptionalInlineElementText(maximum: 180)
      && (1...6).contains(series.count)
      && series.allSatisfy(\.isValid)
      && (1...80).contains(series.reduce(0) { $0 + $1.values.count })
      && (currency == nil || currency?.range(of: "^[A-Za-z]{3}$", options: .regularExpression) != nil)
  }
}

struct InlineChartSeries: Codable, Equatable {
  let name: String
  let values: [InlineChartValue]

  var isValid: Bool {
    name.isInlineElementText(maximum: 50)
      && (1...40).contains(values.count)
      && values.allSatisfy(\.isValid)
  }
}

struct InlineChartValue: Codable, Equatable {
  let label: String
  let value: Double

  var isValid: Bool {
    label.isInlineElementText(maximum: 60) && value.isFinite
  }
}

enum InlineElementTone: String, Codable {
  case neutral, info, positive, warning, negative
}

struct InlineMetrics: Codable, Equatable {
  let title: String?
  let items: [InlineMetric]

  var isValid: Bool {
    title.isOptionalInlineElementText(maximum: 120)
      && (1...6).contains(items.count)
      && items.allSatisfy(\.isValid)
  }
}

struct InlineMetric: Codable, Equatable {
  let label: String
  let value: String
  let detail: String?
  let tone: InlineElementTone?

  var isValid: Bool {
    label.isInlineElementText(maximum: 60)
      && value.isInlineElementText(maximum: 80)
      && detail.isOptionalInlineElementText(maximum: 120)
  }
}

struct InlineCallout: Codable, Equatable {
  let title: String
  let body: String
  let tone: InlineElementTone?

  var isValid: Bool {
    title.isInlineElementText(maximum: 100)
      && body.isInlineElementText(maximum: 600)
  }
}

struct InlineSteps: Codable, Equatable {
  let title: String?
  let items: [InlineStep]

  var isValid: Bool {
    title.isOptionalInlineElementText(maximum: 120)
      && (1...12).contains(items.count)
      && items.allSatisfy(\.isValid)
  }
}

struct InlineStep: Codable, Equatable {
  enum Status: String, Codable { case complete, active, pending, blocked }

  let label: String
  let detail: String?
  let status: Status

  var isValid: Bool {
    label.isInlineElementText(maximum: 100)
      && detail.isOptionalInlineElementText(maximum: 240)
  }
}

enum InlineMessageElementParser {
  private static let maximumPayloadBytes = 40_000

  static func parse(language: String?, text: String) -> InlineMessageElement? {
    guard text.utf8.count <= maximumPayloadBytes else { return nil }
    let language = language?
      .trimmingCharacters(in: .whitespacesAndNewlines)
      .lowercased()
      .replacingOccurrences(of: "_", with: "-")
    guard let data = text.data(using: .utf8) else { return nil }
    let decoder = JSONDecoder()

    switch language {
    case "chart", "heytim-chart":
      guard let value = try? decoder.decode(InlineChart.self, from: data), value.isValid else {
        return nil
      }
      return .chart(value)
    case "metrics", "heytim-metrics":
      guard let value = try? decoder.decode(InlineMetrics.self, from: data), value.isValid else {
        return nil
      }
      return .metrics(value)
    case "callout", "heytim-callout":
      guard let value = try? decoder.decode(InlineCallout.self, from: data), value.isValid else {
        return nil
      }
      return .callout(value)
    case "steps", "heytim-steps":
      guard let value = try? decoder.decode(InlineSteps.self, from: data), value.isValid else {
        return nil
      }
      return .steps(value)
    default:
      return nil
    }
  }
}

private extension String {
  var trimmedForInlineElement: String {
    trimmingCharacters(in: .whitespacesAndNewlines)
  }

  func isInlineElementText(maximum: Int) -> Bool {
    !trimmedForInlineElement.isEmpty && count <= maximum
  }
}

private extension Optional where Wrapped == String {
  func isOptionalInlineElementText(maximum: Int) -> Bool {
    guard let self else { return true }
    return self.isInlineElementText(maximum: maximum)
  }
}

struct InlineMessageElementView: View {
  let element: InlineMessageElement
  let baseColor: Color
  let accentColor: Color

  @ViewBuilder var body: some View {
    switch element {
    case .chart(let chart):
      InlineChartView(chart: chart, baseColor: baseColor, accentColor: accentColor)
    case .metrics(let metrics):
      InlineMetricsView(metrics: metrics, baseColor: baseColor, accentColor: accentColor)
    case .callout(let callout):
      InlineCalloutView(callout: callout, baseColor: baseColor, accentColor: accentColor)
    case .steps(let steps):
      InlineStepsView(steps: steps, baseColor: baseColor, accentColor: accentColor)
    }
  }
}

private struct IndexedChartValue: Identifiable {
  let id: String
  let series: String
  let label: String
  let value: Double
}

private struct InlineChartView: View {
  let chart: InlineChart
  let baseColor: Color
  let accentColor: Color

  private var values: [IndexedChartValue] {
    chart.series.enumerated().flatMap { seriesIndex, series in
      series.values.enumerated().map { valueIndex, item in
        IndexedChartValue(
          id: "\(seriesIndex)-\(valueIndex)", series: series.name,
          label: item.label, value: item.value)
      }
    }
  }

  private var chartWidth: CGFloat {
    max(320, CGFloat(Set(values.map(\.label)).count) * (chart.type == .bar ? 62 : 52))
  }

  private var palette: [Color] {
    [
      accentColor,
      accentColor.opacity(0.68),
      baseColor.opacity(0.78),
      Color.teal,
      Color.orange,
      Color.purple,
    ]
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      VStack(alignment: .leading, spacing: 2) {
        Text(chart.title)
          .froggyFont(.headline, weight: .semibold)
          .foregroundStyle(baseColor)
        if let subtitle = chart.subtitle {
          Text(subtitle)
            .froggyFont(.caption)
            .foregroundStyle(baseColor.opacity(0.68))
        }
      }

      ScrollView(.horizontal) {
        chartBody
          .frame(width: chartWidth, height: 220)
          .padding(.top, 2)
      }
      .scrollIndicators(.visible)
    }
    .inlineElementCard(baseColor: baseColor, accentColor: accentColor)
    .accessibilityIdentifier("chat.element.chart")
  }

  private var chartBody: some View {
    Chart(values) { item in
      switch chart.type {
      case .bar:
        BarMark(
          x: .value("Category", item.label),
          y: .value("Value", item.value)
        )
        .foregroundStyle(by: .value("Series", item.series))
        .position(by: .value("Series", item.series))
        .accessibilityLabel("\(item.series), \(item.label)")
        .accessibilityValue(formatted(item.value))
      case .line:
        LineMark(
          x: .value("Category", item.label),
          y: .value("Value", item.value),
          series: .value("Series", item.series)
        )
        .foregroundStyle(by: .value("Series", item.series))
        .interpolationMethod(.catmullRom)
        .accessibilityLabel("\(item.series), \(item.label)")
        .accessibilityValue(formatted(item.value))
        PointMark(
          x: .value("Category", item.label),
          y: .value("Value", item.value)
        )
        .foregroundStyle(by: .value("Series", item.series))
      case .area:
        AreaMark(
          x: .value("Category", item.label),
          y: .value("Value", item.value),
          series: .value("Series", item.series)
        )
        .foregroundStyle(by: .value("Series", item.series))
        .opacity(0.34)
        .accessibilityLabel("\(item.series), \(item.label)")
        .accessibilityValue(formatted(item.value))
        LineMark(
          x: .value("Category", item.label),
          y: .value("Value", item.value),
          series: .value("Series", item.series)
        )
        .foregroundStyle(by: .value("Series", item.series))
      }
    }
    .chartForegroundStyleScale(
      domain: chart.series.map(\.name),
      range: Array(palette.prefix(chart.series.count)))
    .chartLegend(chart.series.count > 1 ? .visible : .hidden)
    .chartYAxis {
      AxisMarks(position: .leading) { value in
        AxisGridLine().foregroundStyle(baseColor.opacity(0.12))
        AxisTick().foregroundStyle(baseColor.opacity(0.28))
        AxisValueLabel {
          if let number = value.as(Double.self) {
            Text(shortFormatted(number))
              .foregroundStyle(baseColor.opacity(0.68))
          }
        }
      }
    }
    .chartXAxis {
      AxisMarks { _ in
        AxisTick().foregroundStyle(baseColor.opacity(0.28))
        AxisValueLabel().foregroundStyle(baseColor.opacity(0.72))
      }
    }
  }

  private func formatted(_ value: Double) -> String {
    let formatter = NumberFormatter()
    formatter.maximumFractionDigits = 2
    formatter.minimumFractionDigits = 0
    switch chart.format ?? .number {
    case .currency:
      formatter.numberStyle = .currency
      formatter.currencyCode = chart.currency?.uppercased() ?? "USD"
    case .percent:
      formatter.numberStyle = .decimal
      formatter.positiveSuffix = "%"
      formatter.negativeSuffix = "%"
    case .number:
      formatter.numberStyle = .decimal
    }
    return formatter.string(from: NSNumber(value: value)) ?? String(value)
  }

  private func shortFormatted(_ value: Double) -> String {
    let magnitude = abs(value)
    let divisor: Double
    let suffix: String
    if magnitude >= 1_000_000_000 {
      divisor = 1_000_000_000
      suffix = "B"
    } else if magnitude >= 1_000_000 {
      divisor = 1_000_000
      suffix = "M"
    } else if magnitude >= 1_000 {
      divisor = 1_000
      suffix = "K"
    } else {
      divisor = 1
      suffix = ""
    }
    let formatter = NumberFormatter()
    formatter.numberStyle = .decimal
    formatter.maximumFractionDigits = 1
    let number = formatter.string(from: NSNumber(value: value / divisor)) ?? String(value)
    switch chart.format ?? .number {
    case .currency: return "\(currencySymbol)\(number)\(suffix)"
    case .percent: return "\(number)\(suffix)%"
    case .number: return "\(number)\(suffix)"
    }
  }

  private var currencySymbol: String {
    let formatter = NumberFormatter()
    formatter.numberStyle = .currency
    formatter.currencyCode = chart.currency?.uppercased() ?? "USD"
    return formatter.currencySymbol ?? "$"
  }
}

private struct InlineMetricsView: View {
  let metrics: InlineMetrics
  let baseColor: Color
  let accentColor: Color

  private let columns = [GridItem(.adaptive(minimum: 132), spacing: 8)]

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      if let title = metrics.title {
        Text(title)
          .froggyFont(.headline, weight: .semibold)
          .foregroundStyle(baseColor)
      }
      LazyVGrid(columns: columns, alignment: .leading, spacing: 8) {
        ForEach(Array(metrics.items.enumerated()), id: \.offset) { _, item in
          VStack(alignment: .leading, spacing: 4) {
            Text(item.label)
              .froggyFont(.caption, weight: .medium)
              .foregroundStyle(baseColor.opacity(0.66))
            Text(item.value)
              .froggyFont(.title3, weight: .bold)
              .foregroundStyle(baseColor)
              .minimumScaleFactor(0.72)
            if let detail = item.detail {
              Text(detail)
                .froggyFont(.caption, weight: .medium)
                .foregroundStyle(elementColor(item.tone ?? .neutral, accent: accentColor))
            }
          }
          .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
          .padding(10)
          .background(baseColor.opacity(0.045), in: RoundedRectangle(cornerRadius: 9))
          .accessibilityElement(children: .combine)
        }
      }
    }
    .inlineElementCard(baseColor: baseColor, accentColor: accentColor)
    .accessibilityIdentifier("chat.element.metrics")
  }
}

private struct InlineCalloutView: View {
  let callout: InlineCallout
  let baseColor: Color
  let accentColor: Color

  private var tone: InlineElementTone { callout.tone ?? .info }

  var body: some View {
    HStack(alignment: .top, spacing: 10) {
      Image(systemName: elementIcon(tone))
        .froggyFont(.headline)
        .foregroundStyle(elementColor(tone, accent: accentColor))
        .accessibilityHidden(true)
      VStack(alignment: .leading, spacing: 4) {
        Text(callout.title)
          .froggyFont(.headline, weight: .semibold)
          .foregroundStyle(baseColor)
        Text(inlineMarkdown(callout.body))
          .froggyFont(.callout)
          .lineSpacing(2)
          .foregroundStyle(baseColor.opacity(0.82))
      }
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .inlineElementCard(
      baseColor: baseColor, accentColor: elementColor(tone, accent: accentColor))
    .accessibilityElement(children: .combine)
    .accessibilityIdentifier("chat.element.callout")
  }
}

private struct InlineStepsView: View {
  let steps: InlineSteps
  let baseColor: Color
  let accentColor: Color

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      if let title = steps.title {
        Text(title)
          .froggyFont(.headline, weight: .semibold)
          .foregroundStyle(baseColor)
      }
      VStack(alignment: .leading, spacing: 0) {
        ForEach(Array(steps.items.enumerated()), id: \.offset) { index, item in
          HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 0) {
              Image(systemName: stepIcon(item.status))
                .froggyFont(.callout, weight: .semibold)
                .foregroundStyle(stepColor(item.status))
                .frame(width: 20, height: 20)
              if index < steps.items.count - 1 {
                Rectangle()
                  .fill(baseColor.opacity(0.16))
                  .frame(width: 2, height: 30)
              }
            }
            VStack(alignment: .leading, spacing: 2) {
              Text(item.label)
                .froggyFont(.callout, weight: .semibold)
                .foregroundStyle(baseColor)
              if let detail = item.detail {
                Text(inlineMarkdown(detail))
                  .froggyFont(.caption)
                  .foregroundStyle(baseColor.opacity(0.68))
              }
            }
            .padding(.bottom, index < steps.items.count - 1 ? 12 : 0)
          }
          .accessibilityElement(children: .combine)
          .accessibilityValue(item.status.rawValue.capitalized)
        }
      }
    }
    .inlineElementCard(baseColor: baseColor, accentColor: accentColor)
    .accessibilityIdentifier("chat.element.steps")
  }

  private func stepIcon(_ status: InlineStep.Status) -> String {
    switch status {
    case .complete: "checkmark.circle.fill"
    case .active: "circle.inset.filled"
    case .pending: "circle"
    case .blocked: "exclamationmark.circle.fill"
    }
  }

  private func stepColor(_ status: InlineStep.Status) -> Color {
    switch status {
    case .complete: .green
    case .active: accentColor
    case .pending: baseColor.opacity(0.4)
    case .blocked: FrogTheme.danger
    }
  }
}

private func elementColor(_ tone: InlineElementTone, accent: Color) -> Color {
  switch tone {
  case .neutral: .secondary
  case .info: accent
  case .positive: .green
  case .warning: .orange
  case .negative: FrogTheme.danger
  }
}

private func elementIcon(_ tone: InlineElementTone) -> String {
  switch tone {
  case .neutral: "text.bubble.fill"
  case .info: "info.circle.fill"
  case .positive: "checkmark.circle.fill"
  case .warning: "exclamationmark.triangle.fill"
  case .negative: "xmark.octagon.fill"
  }
}

private extension View {
  func inlineElementCard(baseColor: Color, accentColor: Color) -> some View {
    padding(12)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(accentColor.opacity(0.055), in: RoundedRectangle(cornerRadius: 12))
      .overlay {
        RoundedRectangle(cornerRadius: 12)
          .stroke(baseColor.opacity(0.14), lineWidth: 0.5)
      }
  }
}
