import SwiftUI

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

enum FroggyPreferenceKeys {
  static let appearance = "heytim.preferences.appearance"
  static let textSize = "heytim.preferences.text-size"
}

enum FroggyAppearancePreference: String, CaseIterable, Identifiable {
  case system
  case light
  case dark

  var id: String { rawValue }

  var title: String {
    switch self {
    case .system: "System"
    case .light: "Light"
    case .dark: "Dark"
    }
  }

  var colorScheme: ColorScheme? {
    switch self {
    case .system: nil
    case .light: .light
    case .dark: .dark
    }
  }
}

enum FroggyTextSizePreference: String, CaseIterable, Identifiable {
  case system
  case standard
  case large
  case extraLarge

  var id: String { rawValue }

  var title: String {
    switch self {
    case .system: "System"
    case .standard: "Standard"
    case .large: "Large"
    case .extraLarge: "Extra Large"
    }
  }

  func resolvedSize(systemSize: DynamicTypeSize) -> DynamicTypeSize {
    switch self {
    case .system: systemSize
    case .standard: .large
    case .large: .xLarge
    case .extraLarge: .xxLarge
    }
  }

  static var platformDefaultRawValue: String {
    #if os(macOS)
      FroggyTextSizePreference.large.rawValue
    #else
      FroggyTextSizePreference.system.rawValue
    #endif
  }

  var macScale: CGFloat {
    switch self {
    case .system, .standard: 1
    case .large: 1.15
    case .extraLarge: 1.3
    }
  }
}

private struct FroggyTextScaleKey: EnvironmentKey {
  static let defaultValue: CGFloat = 1
}

struct FroggySheetNavigationKey: EnvironmentKey {
  static let defaultValue = false
}

private extension EnvironmentValues {
  var froggyTextScale: CGFloat {
    get { self[FroggyTextScaleKey.self] }
    set { self[FroggyTextScaleKey.self] = newValue }
  }
}

extension EnvironmentValues {
  var froggyUsesSheetNavigation: Bool {
    get { self[FroggySheetNavigationKey.self] }
    set { self[FroggySheetNavigationKey.self] = newValue }
  }
}

private extension Font.TextStyle {
  var froggyMacPointSize: CGFloat {
    if self == .largeTitle { return 28 }
    if self == .title { return 24 }
    if self == .title2 { return 19 }
    if self == .title3 { return 17 }
    if self == .headline { return 15 }
    if self == .subheadline { return 14 }
    if self == .callout { return 14 }
    if self == .footnote || self == .caption || self == .caption2 { return 12 }
    return 15
  }

  var froggyMacDefaultWeight: Font.Weight {
    self == .headline ? .semibold : .regular
  }
}

private struct FroggySemanticFontModifier: ViewModifier {
  @Environment(\.froggyTextScale) private var scale
  let style: Font.TextStyle
  let weight: Font.Weight?
  let design: Font.Design

  func body(content: Content) -> some View {
    #if os(macOS)
      content.font(
        .system(
          size: style.froggyMacPointSize * scale,
          weight: weight ?? style.froggyMacDefaultWeight,
          design: design))
    #else
      content.font(.system(style, design: design, weight: weight))
    #endif
  }
}

private struct FroggyFixedFontModifier: ViewModifier {
  @Environment(\.froggyTextScale) private var scale
  @ScaledMetric private var scaledSize: CGFloat
  let originalSize: CGFloat
  let weight: Font.Weight
  let design: Font.Design

  init(
    size: CGFloat, weight: Font.Weight, design: Font.Design,
    relativeTo style: Font.TextStyle
  ) {
    originalSize = size
    self.weight = weight
    self.design = design
    _scaledSize = ScaledMetric(wrappedValue: size, relativeTo: style)
  }

  func body(content: Content) -> some View {
    #if os(macOS)
      content.font(.system(size: originalSize * scale, weight: weight, design: design))
    #else
      content.font(.system(size: scaledSize, weight: weight, design: design))
    #endif
  }
}

private struct FroggyNavigationTitleModifier: ViewModifier {
  let title: String
  let isPresented: Bool
  let horizontalPadding: CGFloat

  @ViewBuilder func body(content: Content) -> some View {
    #if os(macOS)
      content
        .navigationTitle("")
        .toolbar {
          if isPresented {
            ToolbarItem(placement: .navigation) {
              Text(title)
                .froggyFont(.title3, weight: .semibold)
                .padding(.horizontal, max(horizontalPadding, 12))
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(title)
                .accessibilityAddTraits(.isHeader)
            }
          }
        }
    #else
      content.navigationTitle(isPresented ? title : "")
    #endif
  }
}

public enum FrogTheme {
  // Chief's yellow is a bot identity color, never a default control tint.
  public static let brand = Color(hex: "#FFBC3B")
  public static let brandInk = adaptive(light: RGB(255, 255, 255), dark: RGB(23, 23, 23))
  public static let mascot = Color.primary
  public static let sky = Color(hex: "#3984F6")
  public static let mint = Color(hex: "#58BEAA")
  public static let coral = Color(hex: "#F46A27")
  public static let lavender = Color(hex: "#8A76E8")
  public static let rose = Color(hex: "#E95383")

  private struct RGB {
    let red: CGFloat
    let green: CGFloat
    let blue: CGFloat

    init(_ red: Int, _ green: Int, _ blue: Int) {
      self.red = CGFloat(red) / 255
      self.green = CGFloat(green) / 255
      self.blue = CGFloat(blue) / 255
    }

    init?(hex: String) {
      let value = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
      guard value.count == 6, let number = UInt32(value, radix: 16) else { return nil }
      self.init(Int((number >> 16) & 255), Int((number >> 8) & 255), Int(number & 255))
    }

    var color: Color { Color(red: red, green: green, blue: blue) }

    var luminance: CGFloat {
      func channel(_ value: CGFloat) -> CGFloat {
        value <= 0.04045 ? value / 12.92 : pow((value + 0.055) / 1.055, 2.4)
      }
      return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)
    }

    func blended(toward other: RGB, amount: CGFloat) -> RGB {
      RGB(
        Int(((red * (1 - amount) + other.red * amount) * 255).rounded()),
        Int(((green * (1 - amount) + other.green * amount) * 255).rounded()),
        Int(((blue * (1 - amount) + other.blue * amount) * 255).rounded()))
    }
  }

  private static func adaptive(light: RGB, dark: RGB) -> Color {
    #if os(iOS)
      return Color(
        uiColor: UIColor { traits in
          let value = traits.userInterfaceStyle == .dark ? dark : light
          return UIColor(red: value.red, green: value.green, blue: value.blue, alpha: 1)
        })
    #else
      return Color(
        nsColor: NSColor(name: nil) { appearance in
          let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
          let value = isDark ? dark : light
          return NSColor(
            srgbRed: value.red, green: value.green, blue: value.blue, alpha: 1)
        })
    #endif
  }

  // Opaque neutral layers make the sidebar, reading canvas, and composer distinct.
  public static let accent = Color.primary
  public static let conversationChrome = accent
  public static let activity = adaptive(light: RGB(89, 89, 89), dark: RGB(189, 189, 189))
  public static let canvas = adaptive(light: RGB(255, 255, 255), dark: RGB(23, 23, 23))
  public static let appBackground = canvas
  public static let pageBackground = adaptive(light: RGB(250, 250, 250), dark: RGB(23, 23, 23))
  public static let drawer = adaptive(light: RGB(245, 245, 245), dark: RGB(36, 36, 36))
  public static let surface = adaptive(light: RGB(242, 242, 242), dark: RGB(45, 45, 45))
  public static let border = adaptive(light: RGB(205, 205, 205), dark: RGB(78, 78, 78))
  public static let subtleBorder = adaptive(light: RGB(228, 228, 228), dark: RGB(58, 58, 58))
  public static let assistantBubble = adaptive(light: RGB(245, 245, 245), dark: RGB(43, 43, 43))
  public static let text = Color.primary
  public static let textSoft = Color.primary
  public static let muted = Color.secondary
  public static let mutedWarm = Color.secondary
  // Operational metadata is small and needs more contrast than ordinary secondary copy.
  public static let statusText = Color.primary.opacity(0.68)
  public static let selected = adaptive(light: RGB(231, 231, 231), dark: RGB(59, 59, 59))
  public static let teamBubble = assistantBubble
  public static let teamBorder = border
  public static let approval = assistantBubble
  public static let approvalBorder = border
  public static let danger = Color.red

  // Keep exact bot color for avatars. Small text and thin strokes
  // need a contrast-adjusted shade, particularly for Chief yellow in light mode.
  public static func botReadableColor(_ hex: String, scheme: ColorScheme) -> Color {
    guard let base = RGB(hex: hex) else { return accent }
    let background = scheme == .dark ? RGB(23, 23, 23) : RGB(255, 255, 255)
    let target = scheme == .dark ? RGB(255, 255, 255) : RGB(0, 0, 0)
    for step in 0...20 {
      let candidate = base.blended(toward: target, amount: CGFloat(step) / 20)
      let brighter = max(candidate.luminance, background.luminance)
      let darker = min(candidate.luminance, background.luminance)
      if (brighter + 0.05) / (darker + 0.05) >= 5 { return candidate.color }
    }
    return target.color
  }

  public static func ink(onBotColor hex: String) -> Color {
    botUsesDarkInk(hex) ? .black : .white
  }

  public static func botUsesDarkInk(_ hex: String) -> Bool {
    guard let color = RGB(hex: hex) else { return false }
    return color.luminance > 0.179
  }

  // Compatibility names used by the first native implementation.
  public static let green = accent
  public static let background = canvas
  public static let secondary = muted
}

public struct FrogMark: View {
  var size: CGFloat

  public init(size: CGFloat = 84) { self.size = size }

  public var body: some View {
    TimMark(color: FrogTheme.mascot, ink: FrogTheme.brandInk, eye: FrogTheme.mascot, size: size)
      .accessibilityHidden(true)
  }
}

public struct BotAvatar: View {
  var name: String
  var color: String
  var size: CGFloat

  public init(name: String, color: String, size: CGFloat = 40) {
    self.name = name
    self.color = color
    self.size = size
  }

  public var body: some View {
    TimMark(
      color: Color(hex: color), ink: FrogTheme.ink(onBotColor: color),
      eye: FrogTheme.botUsesDarkInk(color) ? .white : .black, size: size)
    .accessibilityElement(children: .ignore)
    .accessibilityLabel("\(name) bot")
  }
}

public struct BotIdentityLabel: View {
  let name: String
  let color: String
  let detail: String?
  var avatarSize: CGFloat

  public init(
    name: String, color: String, detail: String? = nil, avatarSize: CGFloat = 30
  ) {
    self.name = name
    self.color = color
    self.detail = detail
    self.avatarSize = avatarSize
  }

  public var body: some View {
    HStack(spacing: 10) {
      BotAvatar(name: name, color: color, size: avatarSize)
      VStack(alignment: .leading, spacing: 2) {
        Text(name)
        if let detail, !detail.isEmpty {
          Text(detail)
            .froggyFont(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(2)
        }
      }
    }
    .accessibilityElement(children: .ignore)
    .accessibilityLabel(detail.map { "\(name), \($0)" } ?? name)
  }
}

struct TimMark: View {
  let color: Color
  let ink: Color
  let eye: Color
  let size: CGFloat
  init(
    color: Color, ink: Color = FrogTheme.brandInk,
    eye: Color = FrogTheme.mascot, size: CGFloat
  ) {
    self.color = color
    self.ink = ink
    self.eye = eye
    self.size = size
  }
  var body: some View {
    Canvas { context, _ in
      var context = context
      let scale = size / 100
      context.scaleBy(x: scale, y: scale)

      var antenna = Path()
      antenna.move(to: CGPoint(x: 50, y: 21))
      antenna.addCurve(to: CGPoint(x: 65, y: 7), control1: CGPoint(x: 50, y: 11), control2: CGPoint(x: 56, y: 7))
      context.stroke(antenna, with: .color(ink), style: StrokeStyle(lineWidth: 8, lineCap: .round))
      context.fill(Path(ellipseIn: CGRect(x: 61, y: 0, width: 16, height: 16)), with: .color(color))
      context.fill(Path(ellipseIn: CGRect(x: 66.3, y: 5.3, width: 5.4, height: 5.4)), with: .color(eye))
      context.fill(Path(ellipseIn: CGRect(x: 11, y: 19, width: 78, height: 78)), with: .color(color))
      context.fill(Path(roundedRect: CGRect(x: 18, y: 40, width: 64, height: 38), cornerRadius: 19), with: .color(ink))

      var eyes = Path()
      eyes.move(to: CGPoint(x: 29, y: 62))
      eyes.addCurve(to: CGPoint(x: 41, y: 62), control1: CGPoint(x: 30, y: 55), control2: CGPoint(x: 40, y: 55))
      eyes.move(to: CGPoint(x: 59, y: 62))
      eyes.addCurve(to: CGPoint(x: 71, y: 62), control1: CGPoint(x: 60, y: 55), control2: CGPoint(x: 70, y: 55))
      context.stroke(eyes, with: .color(eye), style: StrokeStyle(lineWidth: 5.5, lineCap: .round))
    }
    .frame(width: size, height: size)
  }
}

public struct PersonAvatar: View {
  let name: String
  var size: CGFloat = 34

  public var body: some View {
    Circle()
      .fill(personColor)
      .overlay(
        Text(name.trimmingCharacters(in: .whitespaces).prefix(1).uppercased())
          .froggyFont(size: max(11, size * 0.4), weight: .bold)
          .foregroundStyle(.white)
      )
      .frame(width: size, height: size)
      .accessibilityLabel("\(name), person")
  }

  private var personColor: Color {
    Color(hex: "#666666")
  }
}

enum ConversationStyle {
  static let sharedGroupAccentHex = "#737373"

  static func accentHex(
    bot: Bot?, group: BotGroup?, activeGroupBotID: String?
  ) -> String {
    if let bot { return bot.color }
    guard let group, let activeGroupBotID, activeGroupBotID != "all" else {
      return sharedGroupAccentHex
    }
    return group.bots.first(where: { $0.id == activeGroupBotID })?.color
      ?? sharedGroupAccentHex
  }
}

public struct GroupAvatar: View {
  let group: BotGroup
  var size: CGFloat = 44

  public var body: some View {
    let tile = size * 0.7
    ZStack {
      if group.bots.count > 1 {
        BotAvatar(name: group.bots[1].name, color: group.bots[1].color, size: tile)
          .offset(x: size * 0.15, y: -size * 0.15)
      } else {
        PersonAvatar(name: group.members.first?.name ?? group.name, size: tile)
          .offset(x: size * 0.15, y: -size * 0.15)
      }
      if let bot = group.bots.first {
        BotAvatar(name: bot.name, color: bot.color, size: tile)
          .offset(x: -size * 0.15, y: size * 0.15)
      } else {
        PersonAvatar(name: group.members.first?.name ?? group.name, size: tile)
          .offset(x: -size * 0.15, y: size * 0.15)
      }
    }
    .frame(width: size, height: size)
    .accessibilityElement(children: .ignore)
    .accessibilityLabel("\(group.name) group")
  }
}

extension Color {
  public init(hex: String) {
    let cleaned = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
    guard cleaned.count == 6, let value = UInt32(cleaned, radix: 16) else {
      self = FrogTheme.accent
      return
    }
    self.init(
      red: Double((value >> 16) & 255) / 255,
      green: Double((value >> 8) & 255) / 255,
      blue: Double(value & 255) / 255)
  }
}

extension View {
  @ViewBuilder func froggyTextSize(
    _ preference: FroggyTextSizePreference, systemSize: DynamicTypeSize
  ) -> some View {
    #if os(macOS)
      environment(\.froggyTextScale, preference.macScale)
        .font(.system(size: 13 * preference.macScale))
    #else
      environment(\.dynamicTypeSize, preference.resolvedSize(systemSize: systemSize))
    #endif
  }

  func froggyFont(
    _ style: Font.TextStyle, weight: Font.Weight? = nil,
    design: Font.Design = .default
  ) -> some View {
    modifier(FroggySemanticFontModifier(style: style, weight: weight, design: design))
  }

  func froggyFont(
    size: CGFloat, weight: Font.Weight = .regular, design: Font.Design = .default,
    relativeTo style: Font.TextStyle = .body
  ) -> some View {
    modifier(
      FroggyFixedFontModifier(
        size: size, weight: weight, design: design, relativeTo: style))
  }

  func froggyNavigationTitle(
    _ title: String, isPresented: Bool = true, horizontalPadding: CGFloat = 0
  ) -> some View {
    modifier(
      FroggyNavigationTitleModifier(
        title: title, isPresented: isPresented, horizontalPadding: horizontalPadding))
  }

  func froggySheetNavigation() -> some View {
    environment(\.froggyUsesSheetNavigation, true)
  }

  @ViewBuilder func froggyComposerSurface(
    tint: Color? = nil, backgroundTint: Color? = nil
  ) -> some View {
    background {
      RoundedRectangle(cornerRadius: 22, style: .continuous)
        .fill(FrogTheme.surface)
        .overlay {
          RoundedRectangle(cornerRadius: 22, style: .continuous)
            .fill((backgroundTint ?? tint)?.opacity(0.06) ?? .clear)
        }
    }
      .overlay(
        RoundedRectangle(cornerRadius: 22, style: .continuous)
          .stroke(tint ?? FrogTheme.border, lineWidth: 1)
      )
  }

  @ViewBuilder func froggySheetSize() -> some View {
    #if os(macOS)
      self.frame(minWidth: 680, idealWidth: 720, minHeight: 560, idealHeight: 680)
    #else
      if #available(iOS 18.0, *) {
        self.presentationSizing(.form)
      } else {
        self
      }
    #endif
  }

  func froggyListSurface() -> some View {
    tint(FrogTheme.accent)
  }
}

public struct EmptyPanel: View {
  let icon: String
  let title: String
  let detail: String

  public init(icon: String, title: String, detail: String) {
    self.icon = icon
    self.title = title
    self.detail = detail
  }

  public var body: some View {
    VStack(spacing: 14) {
      FrogMark(size: 70)
      Text(title).froggyFont(.title, weight: .heavy).foregroundStyle(FrogTheme.text)
      Text(detail).froggyFont(.callout).foregroundStyle(FrogTheme.muted)
        .multilineTextAlignment(.center)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(FrogTheme.appBackground)
  }
}
