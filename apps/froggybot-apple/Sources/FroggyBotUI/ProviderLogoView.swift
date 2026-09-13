import SwiftUI

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

struct ProviderLogoView: View {
  let provider: ConnectionProvider
  var size: CGFloat = 36

  var body: some View {
    ZStack {
      RoundedRectangle(cornerRadius: size * 0.28)
        .fill(.white)
      RoundedRectangle(cornerRadius: size * 0.28)
        .stroke(FrogTheme.subtleBorder, lineWidth: 0.5)
      if hasBundledLogo {
        Image(assetName)
          .resizable()
          .interpolation(.high)
          .scaledToFit()
          .padding(size * 0.13)
      } else {
        Text(provider.iconText)
          .font(.system(size: size * 0.42, weight: .bold))
          .foregroundStyle(FrogTheme.accent)
      }
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }

  private var assetName: String { "Provider-\(provider.id)" }

  private var hasBundledLogo: Bool {
    #if os(iOS)
      UIImage(named: assetName) != nil
    #elseif os(macOS)
      NSImage(named: assetName) != nil
    #endif
  }
}
