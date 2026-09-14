import Foundation
import SwiftUI

enum MarkdownBlock: Equatable {
  case heading(level: Int, text: String)
  case paragraph(String)
  case list(ordered: Bool, items: [MarkdownListItem])
  case quote(String)
  case code(language: String?, text: String)
  case table(MarkdownTable)
  case divider
}

struct MarkdownListItem: Equatable {
  let indentation: Int
  let number: Int?
  let checkbox: Bool?
  var text: String
}

struct MarkdownTable: Equatable {
  let headers: [String]
  let rows: [[String]]
  let alignments: [MarkdownTableAlignment]
}

enum MarkdownTableAlignment: Equatable {
  case leading
  case center
  case trailing
}

enum MarkdownBlockParser {
  static func parse(_ markdown: String) -> [MarkdownBlock] {
    let lines =
      markdown
      .replacingOccurrences(of: "\r\n", with: "\n")
      .replacingOccurrences(of: "\r", with: "\n")
      .components(separatedBy: "\n")
    var blocks: [MarkdownBlock] = []
    var index = 0

    while index < lines.count {
      let line = lines[index]
      if line.trimmingCharacters(in: .whitespaces).isEmpty {
        index += 1
        continue
      }

      if let fence = fence(in: line) {
        var body: [String] = []
        index += 1
        while index < lines.count && !isClosingFence(lines[index], matching: fence) {
          body.append(lines[index])
          index += 1
        }
        if index < lines.count { index += 1 }
        blocks.append(.code(language: fence.language, text: body.joined(separator: "\n")))
        continue
      }

      if let table = table(at: index, in: lines) {
        blocks.append(.table(table.value))
        index = table.nextIndex
        continue
      }

      if let heading = heading(in: line) {
        blocks.append(.heading(level: heading.level, text: heading.text))
        index += 1
        continue
      }

      if isDivider(line) {
        blocks.append(.divider)
        index += 1
        continue
      }

      if quoteText(in: line) != nil {
        var quoteLines: [String] = []
        while index < lines.count, let quoted = quoteText(in: lines[index]) {
          quoteLines.append(quoted)
          index += 1
        }
        blocks.append(.quote(joinProse(quoteLines)))
        continue
      }

      if let firstMarker = listMarker(in: line) {
        let ordered = firstMarker.number != nil
        var items: [MarkdownListItem] = []

        while index < lines.count {
          if let marker = listMarker(in: lines[index]), (marker.number != nil) == ordered {
            items.append(
              MarkdownListItem(
                indentation: marker.indentation,
                number: marker.number,
                checkbox: marker.checkbox,
                text: marker.text))
            index += 1
            continue
          }

          let continuation = lines[index]
          if continuation.trimmingCharacters(in: .whitespaces).isEmpty {
            let nextIndex = index + 1
            if nextIndex < lines.count,
              let nextMarker = listMarker(in: lines[nextIndex]),
              (nextMarker.number != nil) == ordered
            {
              index += 1
              continue
            }
            break
          }

          if leadingWhitespace(in: continuation) > firstMarker.indentation, !items.isEmpty {
            items[items.count - 1].text += " " + continuation.trimmingCharacters(in: .whitespaces)
            index += 1
            continue
          }
          break
        }

        blocks.append(.list(ordered: ordered, items: items))
        continue
      }

      var paragraphLines: [String] = []
      while index < lines.count && !startsBlock(at: index, in: lines) {
        paragraphLines.append(lines[index])
        index += 1
      }
      if paragraphLines.isEmpty {
        paragraphLines.append(line)
        index += 1
      }
      blocks.append(.paragraph(joinProse(paragraphLines)))
    }

    return blocks
  }

  private struct Fence {
    let character: Character
    let length: Int
    let language: String?
  }

  private struct TableResult {
    let value: MarkdownTable
    let nextIndex: Int
  }

  private struct ListMarker {
    let indentation: Int
    let number: Int?
    let checkbox: Bool?
    let text: String
  }

  private static func startsBlock(at index: Int, in lines: [String]) -> Bool {
    let line = lines[index]
    if line.trimmingCharacters(in: .whitespaces).isEmpty { return true }
    if fence(in: line) != nil || heading(in: line) != nil || isDivider(line) { return true }
    if quoteText(in: line) != nil || listMarker(in: line) != nil { return true }
    return table(at: index, in: lines) != nil
  }

  private static func fence(in line: String) -> Fence? {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    guard let character = trimmed.first, character == "`" || character == "~" else {
      return nil
    }
    let length = trimmed.prefix(while: { $0 == character }).count
    guard length >= 3 else { return nil }
    let language = String(trimmed.dropFirst(length)).trimmingCharacters(in: .whitespaces)
    return Fence(character: character, length: length, language: language.isEmpty ? nil : language)
  }

  private static func isClosingFence(_ line: String, matching fence: Fence) -> Bool {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    guard trimmed.prefix(while: { $0 == fence.character }).count >= fence.length else {
      return false
    }
    return trimmed.allSatisfy { $0 == fence.character || $0.isWhitespace }
  }

  private static func heading(in line: String) -> (level: Int, text: String)? {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    let level = trimmed.prefix(while: { $0 == "#" }).count
    guard (1...6).contains(level) else { return nil }
    let contentStart = trimmed.index(trimmed.startIndex, offsetBy: level)
    guard contentStart < trimmed.endIndex, trimmed[contentStart].isWhitespace else { return nil }
    var text = String(trimmed[contentStart...]).trimmingCharacters(in: .whitespaces)
    while text.last == "#" { text.removeLast() }
    text = text.trimmingCharacters(in: .whitespaces)
    return (level, text)
  }

  private static func isDivider(_ line: String) -> Bool {
    let compact = line.filter { !$0.isWhitespace }
    guard compact.count >= 3, let marker = compact.first, ["-", "*", "_"].contains(marker) else {
      return false
    }
    return compact.allSatisfy { $0 == marker }
  }

  private static func quoteText(in line: String) -> String? {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    guard trimmed.first == ">" else { return nil }
    return String(trimmed.dropFirst()).trimmingCharacters(in: .whitespaces)
  }

  private static func listMarker(in line: String) -> ListMarker? {
    let indentation = leadingWhitespace(in: line)
    let content = String(line.drop(while: { $0 == " " || $0 == "\t" }))
    guard !content.isEmpty else { return nil }

    var number: Int?
    var itemText: String
    if ["-", "*", "+"].contains(content.first), content.dropFirst().first?.isWhitespace == true {
      itemText = String(content.dropFirst()).trimmingCharacters(in: .whitespaces)
    } else {
      let digits = content.prefix(while: { $0.isNumber })
      guard !digits.isEmpty, let parsedNumber = Int(digits) else { return nil }
      let punctuationIndex = content.index(content.startIndex, offsetBy: digits.count)
      guard punctuationIndex < content.endIndex,
        content[punctuationIndex] == "." || content[punctuationIndex] == ")"
      else { return nil }
      let afterPunctuation = content.index(after: punctuationIndex)
      guard afterPunctuation < content.endIndex, content[afterPunctuation].isWhitespace else {
        return nil
      }
      number = parsedNumber
      itemText = String(content[afterPunctuation...]).trimmingCharacters(in: .whitespaces)
    }

    var checkbox: Bool?
    let lowered = itemText.lowercased()
    if lowered.hasPrefix("[ ] ") {
      checkbox = false
      itemText = String(itemText.dropFirst(4))
    } else if lowered.hasPrefix("[x] ") {
      checkbox = true
      itemText = String(itemText.dropFirst(4))
    }

    return ListMarker(
      indentation: indentation, number: number, checkbox: checkbox, text: itemText)
  }

  private static func leadingWhitespace(in line: String) -> Int {
    line.prefix(while: { $0 == " " || $0 == "\t" }).reduce(into: 0) { count, character in
      count += character == "\t" ? 4 : 1
    }
  }

  private static func table(at index: Int, in lines: [String]) -> TableResult? {
    guard index + 1 < lines.count,
      let headers = tableCells(in: lines[index]),
      let separators = tableCells(in: lines[index + 1]),
      headers.count == separators.count,
      !headers.isEmpty
    else { return nil }

    let alignments = separators.compactMap(tableAlignment)
    guard alignments.count == separators.count else { return nil }

    var rows: [[String]] = []
    var cursor = index + 2
    while cursor < lines.count,
      !lines[cursor].trimmingCharacters(in: .whitespaces).isEmpty,
      let cells = tableCells(in: lines[cursor])
    {
      rows.append(normalized(cells, count: headers.count))
      cursor += 1
    }

    return TableResult(
      value: MarkdownTable(
        headers: headers, rows: rows, alignments: alignments),
      nextIndex: cursor)
  }

  private static func tableCells(in line: String) -> [String]? {
    var source = line.trimmingCharacters(in: .whitespaces)
    guard source.contains("|") else { return nil }
    if source.first == "|" { source.removeFirst() }
    if source.last == "|" { source.removeLast() }

    var cells = [""]
    var escaped = false
    var inCode = false
    for character in source {
      if escaped {
        cells[cells.count - 1].append(character)
        escaped = false
      } else if character == "\\" {
        escaped = true
      } else if character == "`" {
        inCode.toggle()
        cells[cells.count - 1].append(character)
      } else if character == "|" && !inCode {
        cells.append("")
      } else {
        cells[cells.count - 1].append(character)
      }
    }
    if escaped { cells[cells.count - 1].append("\\") }
    guard cells.count > 1 else { return nil }
    return cells.map { $0.trimmingCharacters(in: .whitespaces) }
  }

  private static func tableAlignment(_ separator: String) -> MarkdownTableAlignment? {
    var value = separator.trimmingCharacters(in: .whitespaces)
    let leadingColon = value.first == ":"
    let trailingColon = value.last == ":"
    if leadingColon { value.removeFirst() }
    if trailingColon, !value.isEmpty { value.removeLast() }
    guard value.count >= 3, value.allSatisfy({ $0 == "-" }) else { return nil }
    if leadingColon && trailingColon { return .center }
    if trailingColon { return .trailing }
    return .leading
  }

  private static func normalized(_ cells: [String], count: Int) -> [String] {
    if cells.count == count { return cells }
    if cells.count > count { return Array(cells.prefix(count)) }
    return cells + Array(repeating: "", count: count - cells.count)
  }

  private static func joinProse(_ lines: [String]) -> String {
    var result = ""
    var previousLineForcedBreak = false
    for line in lines {
      let trimmed = line.trimmingCharacters(in: .whitespaces)
      if result.isEmpty {
        result = trimmed
        previousLineForcedBreak = line.hasSuffix("  ")
        continue
      }
      result += (previousLineForcedBreak ? "\n" : " ") + trimmed
      previousLineForcedBreak = line.hasSuffix("  ")
    }
    return result
  }
}

struct MarkdownMessageView: View {
  private let blocks: [MarkdownBlock]
  private let expandsToFill: Bool
  private let baseColor: Color

  init(_ markdown: String, expandsToFill: Bool = true, baseColor: Color) {
    blocks = MarkdownBlockParser.parse(markdown)
    self.expandsToFill = expandsToFill
    self.baseColor = baseColor
  }

  var body: some View {
    Group {
      if expandsToFill {
        content.frame(maxWidth: .infinity, alignment: .leading)
      } else {
        content
      }
    }
    .textSelection(.enabled)
  }

  private var content: some View {
    VStack(alignment: .leading, spacing: 12) {
      ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
        MarkdownBlockView(block: block, baseColor: baseColor)
      }
    }
  }
}

private struct MarkdownBlockView: View {
  let block: MarkdownBlock
  let baseColor: Color

  @ViewBuilder var body: some View {
    switch block {
    case .heading(let level, let text):
      Text(inlineMarkdown(text))
        .froggyFont(headingStyle(level), weight: headingWeight(level))
        .foregroundStyle(baseColor)
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityAddTraits(.isHeader)
    case .paragraph(let text):
      Text(inlineMarkdown(text))
        .froggyFont(.body)
        .lineSpacing(3)
        .foregroundStyle(baseColor)
        .fixedSize(horizontal: false, vertical: true)
    case .list(let ordered, let items):
      list(ordered: ordered, items: items)
    case .quote(let text):
      HStack(alignment: .top, spacing: 10) {
        Capsule()
          .fill(FrogTheme.accent.opacity(0.75))
          .frame(width: 3)
        Text(inlineMarkdown(text))
          .froggyFont(.body)
          .italic()
          .lineSpacing(3)
          .foregroundStyle(baseColor.opacity(0.78))
          .fixedSize(horizontal: false, vertical: true)
      }
      .padding(.vertical, 2)
    case .code(let language, let text):
      code(language: language, text: text)
    case .table(let table):
      markdownTable(table)
    case .divider:
      Divider()
        .overlay(baseColor.opacity(0.22))
    }
  }

  private func headingStyle(_ level: Int) -> Font.TextStyle {
    switch level {
    case 1: .title2
    case 2: .title3
    case 3: .headline
    case 4: .body
    default: .callout
    }
  }

  private func headingWeight(_ level: Int) -> Font.Weight? {
    level == 3 ? nil : level <= 2 ? .bold : .semibold
  }

  private func list(ordered: Bool, items: [MarkdownListItem]) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      ForEach(Array(items.enumerated()), id: \.offset) { index, item in
        HStack(alignment: .firstTextBaseline, spacing: 8) {
          Group {
            if let checked = item.checkbox {
              Image(systemName: checked ? "checkmark.square.fill" : "square")
                .accessibilityLabel(checked ? "Completed" : "Not completed")
            } else {
              Text(ordered ? "\(item.number ?? index + 1)." : "•")
            }
          }
          .froggyFont(.body, weight: .semibold)
          .foregroundStyle(baseColor.opacity(0.72))
          .frame(width: 22, alignment: .trailing)

          Text(inlineMarkdown(item.text))
            .froggyFont(.body)
            .lineSpacing(3)
            .foregroundStyle(baseColor)
            .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.leading, CGFloat(min(item.indentation / 2, 4)) * 14)
      }
    }
  }

  private func code(language: String?, text: String) -> some View {
    VStack(alignment: .leading, spacing: 0) {
      if let language {
        Text(language.uppercased())
          .froggyFont(.caption2, weight: .semibold)
          .foregroundStyle(baseColor.opacity(0.58))
          .padding(.horizontal, 11)
          .padding(.top, 8)
      }
      ScrollView(.horizontal) {
        Text(text)
          .froggyFont(.callout, design: .monospaced)
          .foregroundStyle(baseColor)
          .padding(11)
          .fixedSize(horizontal: true, vertical: false)
      }
      .scrollIndicators(.visible)
    }
    .background(baseColor.opacity(0.07), in: RoundedRectangle(cornerRadius: 10))
    .overlay {
      RoundedRectangle(cornerRadius: 10)
        .stroke(baseColor.opacity(0.14), lineWidth: 0.5)
    }
  }

  private func markdownTable(_ table: MarkdownTable) -> some View {
    ScrollView(.horizontal) {
      Grid(alignment: .leading, horizontalSpacing: 0, verticalSpacing: 0) {
        GridRow {
          ForEach(Array(table.headers.enumerated()), id: \.offset) { column, header in
            tableCell(
              header, alignment: table.alignments[column], isHeader: true, isAlternate: false)
          }
        }
        ForEach(Array(table.rows.enumerated()), id: \.offset) { rowIndex, row in
          GridRow {
            ForEach(Array(row.enumerated()), id: \.offset) { column, value in
              tableCell(
                value,
                alignment: table.alignments[column],
                isHeader: false,
                isAlternate: rowIndex.isMultiple(of: 2))
            }
          }
        }
      }
      .clipShape(RoundedRectangle(cornerRadius: 10))
      .overlay {
        RoundedRectangle(cornerRadius: 10)
          .stroke(baseColor.opacity(0.16), lineWidth: 0.5)
      }
    }
    .scrollIndicators(.visible)
    .accessibilityElement(children: .contain)
  }

  private func tableCell(
    _ text: String,
    alignment: MarkdownTableAlignment,
    isHeader: Bool,
    isAlternate: Bool
  ) -> some View {
    Text(inlineMarkdown(text))
      .froggyFont(.callout, weight: isHeader ? .semibold : nil)
      .lineSpacing(2)
      .foregroundStyle(baseColor)
      .frame(minWidth: 90, maxWidth: 240, alignment: frameAlignment(alignment))
      .padding(.horizontal, 10)
      .padding(.vertical, 8)
      .background(baseColor.opacity(isHeader ? 0.12 : (isAlternate ? 0.045 : 0.015)))
  }

  private func frameAlignment(_ alignment: MarkdownTableAlignment) -> Alignment {
    switch alignment {
    case .leading: .leading
    case .center: .center
    case .trailing: .trailing
    }
  }
}

func inlineMarkdown(_ markdown: String) -> AttributedString {
  (try? AttributedString(
    markdown: markdown, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
    ?? AttributedString(markdown)
}
