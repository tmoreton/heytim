import SwiftUI

public enum FrogTheme {
  public static let brand = Color(hex: "#007A3D")
  public static let brandDark = Color(hex: "#006633")
  public static let canvas = Color(hex: "#F4F2EC")
  public static let appBackground = Color(hex: "#FBFBF9")
  public static let pageBackground = Color(hex: "#F8F7F3")
  public static let drawer = Color(hex: "#F2F1ED")
  public static let surface = Color.white
  public static let text = Color(hex: "#171714")
  public static let textSoft = Color(hex: "#24231F")
  public static let muted = Color(hex: "#6E6A62")
  public static let mutedWarm = Color(hex: "#77736B")
  public static let border = Color(hex: "#DEDAD0")
  public static let subtleBorder = Color(hex: "#E7E3DA")
  public static let selected = Color(hex: "#E4F1EA")
  public static let assistantBubble = Color(hex: "#EFEFEC")
  public static let teamBubble = Color(hex: "#E9F4EE")
  public static let teamBorder = Color(hex: "#A8CFB9")
  public static let approval = Color(hex: "#FFF7DF")
  public static let approvalBorder = Color(hex: "#E7C86A")
  public static let danger = Color(hex: "#A53A32")

  // Compatibility names used by the first native implementation.
  public static let green = brand
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

struct FroggyPrimaryButtonStyle: ButtonStyle {
  @Environment(\.isEnabled) private var isEnabled

  func makeBody(configuration: Configuration) -> some View {
    configuration.label
      .font(.system(size: 16, weight: .semibold))
      .foregroundStyle(.white)
      .frame(maxWidth: .infinity, minHeight: 56)
      .background(FrogTheme.brand, in: RoundedRectangle(cornerRadius: 16))
      .opacity(!isEnabled ? 0.45 : configuration.isPressed ? 0.78 : 1)
  }
}

struct FroggySecondaryButtonStyle: ButtonStyle {
  @Environment(\.isEnabled) private var isEnabled

  func makeBody(configuration: Configuration) -> some View {
    configuration.label
      .font(.system(size: 13, weight: .bold))
      .foregroundStyle(FrogTheme.brandDark)
      .padding(.horizontal, 13)
      .frame(minHeight: 40)
      .background(FrogTheme.surface, in: RoundedRectangle(cornerRadius: 12))
      .overlay(RoundedRectangle(cornerRadius: 12).stroke(FrogTheme.border))
      .opacity(!isEnabled ? 0.45 : configuration.isPressed ? 0.7 : 1)
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
  @ViewBuilder func froggySheetSize() -> some View {
    #if os(macOS)
      self.frame(minWidth: 560, idealWidth: 680, minHeight: 520, idealHeight: 680)
    #else
      self
    #endif
  }

  func froggyListSurface() -> some View {
    scrollContentBackground(.hidden)
      .background(FrogTheme.pageBackground)
      .foregroundStyle(FrogTheme.text)
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
