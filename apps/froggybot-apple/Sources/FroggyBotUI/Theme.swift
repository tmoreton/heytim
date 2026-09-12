import SwiftUI

public enum FrogTheme {
  public static let green = Color(red: 0, green: 0.48, blue: 0.24)
  public static let background = Color(red: 0.957, green: 0.949, blue: 0.925)
  public static let secondary = Color(red: 0.45, green: 0.43, blue: 0.39)
  public static let border = Color(red: 0.90, green: 0.88, blue: 0.84)
}

public struct BotAvatar: View {
  var name: String
  var color: String
  var size: CGFloat = 40
  public init(name: String, color: String, size: CGFloat = 40) {
    self.name = name
    self.color = color
    self.size = size
  }
  public var body: some View {
    ZStack {
      Circle().fill(Color(hex: color))
      Text(name.prefix(1).uppercased()).font(.system(size: size * 0.4, weight: .bold))
        .foregroundStyle(.white)
    }.frame(width: size, height: size).accessibilityHidden(true)
  }
}

extension Color {
  public init(hex: String) {
    let cleaned = hex.trimmingCharacters(in: CharacterSet.alphanumerics.inverted)
    var value: UInt64 = 0
    Scanner(string: cleaned).scanHexInt64(&value)
    let r: Double
    let g: Double
    let b: Double
    if cleaned.count == 6 {
      r = Double((value >> 16) & 255) / 255
      g = Double((value >> 8) & 255) / 255
      b = Double(value & 255) / 255
    } else {
      r = 0
      g = 0.48
      b = 0.24
    }
    self.init(red: r, green: g, blue: b)
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
    ContentUnavailableView(title, systemImage: icon, description: Text(detail))
  }
}
