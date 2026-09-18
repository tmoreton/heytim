import SwiftUI

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

enum FroggyPreferenceKeys {
  static let appearance = "froggybot.preferences.appearance"
  static let textSize = "froggybot.preferences.text-size"
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
    if self == .largeTitle { return 26 }
    if self == .title { return 22 }
    if self == .title2 { return 17 }
    if self == .title3 { return 15 }
    if self == .headline { return 13 }
    if self == .subheadline { return 11 }
    if self == .callout { return 12 }
    if self == .footnote || self == .caption || self == .caption2 { return 10 }
    return 13
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
  // Tim's amber identity uses a deeper tone for readable controls on light surfaces.
  public static let brand = Color(hex: "#A15B00")
  public static let brandDark = Color(hex: "#754100")
  public static let mascot = Color(hex: "#FFBC3B")
  public static let accent: Color = {
    #if os(iOS)
      Color(
        uiColor: UIColor { traits in
          traits.userInterfaceStyle == .dark
            ? UIColor(red: 1, green: 196 / 255, blue: 87 / 255, alpha: 1)
            : UIColor(red: 161 / 255, green: 91 / 255, blue: 0, alpha: 1)
        })
    #else
      Color(
        nsColor: NSColor(name: nil) { appearance in
          let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
          return isDark
            ? NSColor(srgbRed: 1, green: 196 / 255, blue: 87 / 255, alpha: 1)
            : NSColor(srgbRed: 161 / 255, green: 91 / 255, blue: 0, alpha: 1)
        })
    #endif
  }()
  #if os(iOS)
    public static let canvas = Color(uiColor: .systemGroupedBackground)
    public static let appBackground = Color(uiColor: .systemBackground)
    public static let pageBackground = Color(uiColor: .secondarySystemGroupedBackground)
    public static let drawer = Color(uiColor: .systemGroupedBackground)
    public static let surface = Color(uiColor: .secondarySystemBackground)
    public static let border = Color(uiColor: .separator)
    public static let subtleBorder = Color(uiColor: .quaternaryLabel)
    public static let assistantBubble = Color(uiColor: .secondarySystemBackground)
  #else
    public static let canvas = Color(nsColor: .underPageBackgroundColor)
    public static let appBackground = Color(nsColor: .windowBackgroundColor)
    public static let pageBackground = Color(nsColor: .underPageBackgroundColor)
    public static let drawer = Color(nsColor: .controlBackgroundColor)
    public static let surface = Color(nsColor: .controlBackgroundColor)
    public static let border = Color(nsColor: .separatorColor)
    public static let subtleBorder = Color(nsColor: .quaternaryLabelColor)
    public static let assistantBubble = Color(nsColor: .controlBackgroundColor)
  #endif
  public static let text = Color.primary
  public static let textSoft = Color.primary
  public static let muted = Color.secondary
  public static let mutedWarm = Color.secondary
  // Operational metadata is small and needs more contrast than ordinary secondary copy.
  public static let statusText = Color.primary.opacity(0.68)
  public static let selected = accent.opacity(0.12)
  public static let teamBubble = accent.opacity(0.10)
  public static let teamBorder = accent.opacity(0.35)
  public static let approval = Color.yellow.opacity(0.16)
  public static let approvalBorder = Color.orange.opacity(0.55)
  public static let danger = Color.red

  // Compatibility names used by the first native implementation.
  public static let green = accent
  public static let background = canvas
  public static let secondary = muted
}

public struct FrogMark: View {
  var size: CGFloat

  public init(size: CGFloat = 84) { self.size = size }

  public var body: some View {
    TimMark(color: FrogTheme.mascot, size: size)
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
    TimMark(color: Color(hex: color), size: size)
    .accessibilityElement(children: .ignore)
    .accessibilityLabel("\(name) bot")
  }
}

private struct TimMark: View {
  let color: Color
  let size: CGFloat

  var body: some View {
    Canvas { context, _ in
      var context = context
      let scale = size / 100
      context.scaleBy(x: scale, y: scale)
      let ink = Color(hex: "#252829")
      let white = Color(hex: "#FFFDF8")

      var antenna = Path()
      antenna.move(to: CGPoint(x: 50, y: 21))
      antenna.addCurve(to: CGPoint(x: 65, y: 7), control1: CGPoint(x: 50, y: 11), control2: CGPoint(x: 56, y: 7))
      context.stroke(antenna, with: .color(ink), style: StrokeStyle(lineWidth: 8, lineCap: .round))
      context.fill(Path(ellipseIn: CGRect(x: 61, y: 0, width: 16, height: 16)), with: .color(color))
      context.fill(Path(ellipseIn: CGRect(x: 66.3, y: 5.3, width: 5.4, height: 5.4)), with: .color(white))
      context.fill(Path(ellipseIn: CGRect(x: 11, y: 19, width: 78, height: 78)), with: .color(color))
      context.fill(Path(roundedRect: CGRect(x: 18, y: 40, width: 64, height: 38), cornerRadius: 19), with: .color(ink))

      var eyes = Path()
      eyes.move(to: CGPoint(x: 29, y: 62))
      eyes.addCurve(to: CGPoint(x: 41, y: 62), control1: CGPoint(x: 30, y: 55), control2: CGPoint(x: 40, y: 55))
      eyes.move(to: CGPoint(x: 59, y: 62))
      eyes.addCurve(to: CGPoint(x: 71, y: 62), control1: CGPoint(x: 60, y: 55), control2: CGPoint(x: 70, y: 55))
      context.stroke(eyes, with: .color(white), style: StrokeStyle(lineWidth: 5.5, lineCap: .round))
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
    let palette = ["#2F6FA3", "#7A52A3", "#B85D3B", "#436F5A", "#9A6A24"]
    let sum = name.unicodeScalars.reduce(0) { $0 + Int($1.value) }
    return Color(hex: palette[sum % palette.count])
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
    var value: UInt64 = 0
    Scanner(string: cleaned).scanHexInt64(&value)
    guard cleaned.count == 6 else {
      self = FrogTheme.brand
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

  @ViewBuilder func froggyGlassButton(prominent: Bool = false, tint: Color? = nil) -> some View {
    if #available(iOS 26.0, macOS 26.0, *) {
      if prominent {
        buttonStyle(.glassProminent).tint(tint)
      } else {
        buttonStyle(.glass)
      }
    } else if prominent {
      buttonStyle(.borderedProminent).tint(tint)
    } else {
      buttonStyle(.bordered).tint(tint)
    }
  }

  @ViewBuilder func froggyComposerSurface() -> some View {
    background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
      .overlay(
        RoundedRectangle(cornerRadius: 22, style: .continuous)
          .stroke(FrogTheme.border.opacity(0.7), lineWidth: 0.5)
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
