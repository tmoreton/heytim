import Foundation
import SwiftUI

struct InlineFlow: Codable, Equatable {
  let title: String
  let nodes: [InlineFlowNode]

  var isValid: Bool {
    title.isInlineElementText(maximum: 120)
      && (2...6).contains(nodes.count)
      && nodes.allSatisfy(\.isValid)
  }
}

struct InlineFlowNode: Codable, Equatable {
  let label: String
  let detail: String?
  let nextLabel: String?

  var isValid: Bool {
    label.isInlineElementText(maximum: 70)
      && detail.isOptionalInlineElementText(maximum: 150)
      && nextLabel.isOptionalInlineElementText(maximum: 50)
  }
}


struct InlineFlowView: View {
  let flow: InlineFlow
  let baseColor: Color
  let accentColor: Color

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text(flow.title)
        .froggyFont(.headline, weight: .semibold)
        .foregroundStyle(baseColor)
      ScrollView(.horizontal) {
        HStack(alignment: .center, spacing: 8) {
          ForEach(Array(flow.nodes.enumerated()), id: \.offset) { index, node in
            flowNode(node)
            if index < flow.nodes.count - 1 {
              flowConnector(node.nextLabel)
            }
          }
        }
      }
      .scrollIndicators(.visible)
    }
    .inlineElementCard(baseColor: baseColor, accentColor: accentColor)
    .accessibilityIdentifier("chat.element.flow")
  }

  private func flowNode(_ node: InlineFlowNode) -> some View {
    VStack(alignment: .leading, spacing: 5) {
      Text(node.label)
        .froggyFont(.callout, weight: .semibold)
        .foregroundStyle(baseColor)
      if let detail = node.detail {
        Text(detail)
          .froggyFont(.caption)
          .foregroundStyle(baseColor.opacity(0.72))
      }
    }
    .frame(width: 150, alignment: .leading)
    .frame(minHeight: 74, alignment: .leading)
    .padding(10)
    .background(baseColor.opacity(0.055), in: RoundedRectangle(cornerRadius: 10))
    .overlay {
      RoundedRectangle(cornerRadius: 10)
        .stroke(accentColor.opacity(0.32), lineWidth: 1)
    }
    .accessibilityElement(children: .combine)
  }

  private func flowConnector(_ label: String?) -> some View {
    VStack(spacing: 2) {
      if let label {
        Text(label)
          .froggyFont(.caption)
          .foregroundStyle(baseColor.opacity(0.7))
      }
      Image(systemName: "arrow.right")
        .foregroundStyle(accentColor)
    }
    .frame(width: 68)
    .accessibilityLabel(label ?? "Next")
  }
}
