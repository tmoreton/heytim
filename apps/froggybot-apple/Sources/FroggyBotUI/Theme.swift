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
}

public enum FrogTheme {
  // Keep the original, darker FroggyBot green for filled surfaces where white text sits on top.
  public static let brand = Color(hex: "#007A3D")
  public static let brandDark = Color(hex: "#006633")
  // Interactive controls and green text need a lighter green on dark system surfaces.
  public static let accent: Color = {
    #if os(iOS)
      Color(
        uiColor: UIColor { traits in
          traits.userInterfaceStyle == .dark
            ? UIColor(red: 87 / 255, green: 224 / 255, blue: 140 / 255, alpha: 1)
            : UIColor(red: 0, green: 122 / 255, blue: 61 / 255, alpha: 1)
        })
    #else
      Color(
        nsColor: NSColor(name: nil) { appearance in
          let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
          return isDark
            ? NSColor(srgbRed: 87 / 255, green: 224 / 255, blue: 140 / 255, alpha: 1)
            : NSColor(srgbRed: 0, green: 122 / 255, blue: 61 / 255, alpha: 1)
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
    Image("FrogLogo")
      .resizable()
      .interpolation(.high)
      .scaledToFit()
      .frame(width: size, height: size)
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
    ZStack {
      Image("FrogLogo")
        .resizable()
        .renderingMode(.template)
        .foregroundStyle(Color(hex: color))
        .scaledToFit()
      AvatarFace(color: Color(hex: color))
    }
    .frame(width: size, height: size)
    .accessibilityElement(children: .ignore)
    .accessibilityLabel("\(name) bot")
  }
}

private struct AvatarFace: View {
  let color: Color

  var body: some View {
    GeometryReader { geometry in
      let side = min(geometry.size.width, geometry.size.height)
      ZStack {
        eye(at: CGPoint(x: side * 0.295, y: side * 0.348), side: side)
        eye(at: CGPoint(x: side * 0.705, y: side * 0.348), side: side)
        SmileShape()
          .stroke(.white, style: StrokeStyle(lineWidth: max(2, side * 0.057), lineCap: .round))
          .frame(width: side, height: side)
      }
    }
  }

  private func eye(at point: CGPoint, side: CGFloat) -> some View {
    ZStack {
      Circle().fill(.white).frame(width: side * 0.19, height: side * 0.19)
      ZStack(alignment: .topTrailing) {
        Circle().fill(color)
        Circle().fill(.white).frame(width: side * 0.03, height: side * 0.03)
          .padding(side * 0.006)
      }
      .frame(width: side * 0.084, height: side * 0.084)
    }
    .position(point)
  }
}

private struct SmileShape: Shape {
  func path(in rect: CGRect) -> Path {
    var path = Path()
    path.move(to: CGPoint(x: rect.width * 0.365, y: rect.height * 0.595))
    path.addQuadCurve(
      to: CGPoint(x: rect.width * 0.635, y: rect.height * 0.595),
      control: CGPoint(x: rect.width * 0.5, y: rect.height * 0.73))
    return path
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
          .font(.system(size: max(11, size * 0.4), weight: .bold))
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
      Text(title).font(.system(size: 22, weight: .heavy)).foregroundStyle(FrogTheme.text)
      Text(detail).font(.system(size: 14)).foregroundStyle(FrogTheme.muted)
        .multilineTextAlignment(.center)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(FrogTheme.appBackground)
  }
}
