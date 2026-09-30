import SwiftUI

extension View {
  func froggyGlassButton(prominent: Bool = false, tint: Color? = nil) -> some View {
    modifier(FroggyGlassButtonModifier(prominent: prominent, customTint: tint))
  }
}

private struct FroggyGlassButtonModifier: ViewModifier {
  @Environment(\.colorScheme) private var colorScheme
  let prominent: Bool
  let customTint: Color?

  @ViewBuilder func body(content: Content) -> some View {
    let fill = customTint ?? (colorScheme == .dark ? Color.white : Color.black)
    if prominent {
      #if os(macOS)
        content.buttonStyle(FroggyPrimaryButtonStyle(fill: fill))
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

    func makeBody(configuration: Configuration) -> some View {
      configuration.label
        .foregroundStyle(colorScheme == .dark ? Color.black : Color.white)
        .padding(.horizontal, 13)
        .padding(.vertical, 7)
        .background(fill, in: Capsule())
        .opacity(isEnabled ? (configuration.isPressed ? 0.75 : 1) : 0.45)
        .contentShape(Capsule())
    }
  }
#endif
