import SwiftUI

extension View {
  func froggyGlassButton(
    prominent: Bool = false, tint: Color? = nil, cornerRadius: CGFloat? = nil
  ) -> some View {
    modifier(
      FroggyGlassButtonModifier(
        prominent: prominent, customTint: tint, cornerRadius: cornerRadius))
  }
}

private struct FroggyGlassButtonModifier: ViewModifier {
  @Environment(\.colorScheme) private var colorScheme
  let prominent: Bool
  let customTint: Color?
  let cornerRadius: CGFloat?

  @ViewBuilder func body(content: Content) -> some View {
    let fill = customTint ?? (colorScheme == .dark ? Color.white : Color.black)
    if prominent {
      #if os(macOS)
        content.buttonStyle(FroggyPrimaryButtonStyle(fill: fill, cornerRadius: cornerRadius))
      #else
        content
          .buttonStyle(.borderedProminent)
          .tint(fill)
          .foregroundStyle(colorScheme == .dark ? Color.black : Color.white)
      #endif
    } else {
      content.buttonStyle(.bordered).tint(fill)
    }
  }
}

#if os(macOS)
  private struct FroggyPrimaryButtonStyle: ButtonStyle {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.isEnabled) private var isEnabled
    let fill: Color
    let cornerRadius: CGFloat?

    func makeBody(configuration: Configuration) -> some View {
      let shape = RoundedRectangle(cornerRadius: cornerRadius ?? 100, style: .continuous)
      return configuration.label
        .foregroundStyle(colorScheme == .dark ? Color.black : Color.white)
        .padding(.horizontal, 13)
        .padding(.vertical, 7)
        .background(fill, in: shape)
        .opacity(isEnabled ? (configuration.isPressed ? 0.75 : 1) : 0.45)
        .contentShape(shape)
    }
  }
#endif
