import SwiftUI

#if os(iOS)
  import UIKit
#elseif os(macOS)
  import AppKit
#endif

struct ProviderLogoView: View {
  let providerID: String
  let iconText: String
  let size: CGFloat

  init(provider: ConnectionProvider, size: CGFloat = 36) {
    providerID = provider.id
    iconText = provider.iconText
    self.size = size
  }

  init(providerID: String, iconText: String, size: CGFloat = 36) {
    self.providerID = providerID
    self.iconText = iconText
    self.size = size
  }

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
        Text(iconText)
          .froggyFont(size: size * 0.42, weight: .bold)
          .foregroundStyle(FrogTheme.accent)
      }
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }

  private var assetName: String { "Provider-\(providerID)" }

  private var hasBundledLogo: Bool {
    #if os(iOS)
      UIImage(named: assetName) != nil
    #elseif os(macOS)
      NSImage(named: assetName) != nil
    #endif
  }
}
