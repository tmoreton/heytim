Pod::Spec.new do |s|
  s.name             = 'FroggyBotTranscription'
  s.version          = '0.1.0'
  s.summary          = 'Private on-device Nemotron transcription for FroggyBot'
  s.description      = 'An Expo bridge over a reusable Apple sherpa-onnx and Nemotron transcription core.'
  s.license          = { :type => 'Proprietary' }
  s.author           = 'FroggyBot'
  s.homepage         = 'https://froggybot.com'
  s.platforms        = { :ios => '17.0' }
  s.swift_version    = '5.9'
  s.source           = { :path => '.' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'
  s.source_files = 'Core/**/*.swift', 'Expo/**/*.swift'
  s.resource_bundles = {
    'FroggyBotNemotronResources' => [
      'Generated/Models/nemotron-3.5-asr-streaming-0.6b-1120ms',
      'Generated/Notices/OpenMDW-1.1.txt',
      'Notices/THIRD_PARTY_NOTICES.md'
    ]
  }
  # Both dependencies are static XCFrameworks. Linking their selected framework
  # slices directly avoids a CocoaPods staging collision when two differently
  # named XCFramework archives belong to one local pod target.
  s.frameworks = \
    'AVFoundation', 'Accelerate', 'CoreFoundation', 'CoreML', 'Foundation', \
    'SherpaOnnxC', 'onnxruntime'
  s.libraries = 'c++'
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule',
    'FRAMEWORK_SEARCH_PATHS[sdk=iphoneos*]' => '$(inherited) "${PODS_TARGET_SRCROOT}/Generated/Frameworks/iOS/sherpa-onnx.xcframework/ios-arm64" "${PODS_TARGET_SRCROOT}/Generated/Frameworks/iOS/onnxruntime.xcframework/ios-arm64"',
    'FRAMEWORK_SEARCH_PATHS[sdk=iphonesimulator*]' => '$(inherited) "${PODS_TARGET_SRCROOT}/Generated/Frameworks/iOS/sherpa-onnx.xcframework/ios-arm64_x86_64-simulator" "${PODS_TARGET_SRCROOT}/Generated/Frameworks/iOS/onnxruntime.xcframework/ios-arm64_x86_64-simulator"'
  }
  s.user_target_xcconfig = {
    # PODS_TARGET_SRCROOT is scoped to the pod target and is empty when these
    # settings are inherited by the app target. Resolve the shared workspace
    # package from PODS_ROOT instead so device and simulator links are stable.
    'FRAMEWORK_SEARCH_PATHS[sdk=iphoneos*]' => '$(inherited) "${PODS_ROOT}/../../../../packages/frogbot-transcription/ios/Generated/Frameworks/iOS/sherpa-onnx.xcframework/ios-arm64" "${PODS_ROOT}/../../../../packages/frogbot-transcription/ios/Generated/Frameworks/iOS/onnxruntime.xcframework/ios-arm64"',
    'FRAMEWORK_SEARCH_PATHS[sdk=iphonesimulator*]' => '$(inherited) "${PODS_ROOT}/../../../../packages/frogbot-transcription/ios/Generated/Frameworks/iOS/sherpa-onnx.xcframework/ios-arm64_x86_64-simulator" "${PODS_ROOT}/../../../../packages/frogbot-transcription/ios/Generated/Frameworks/iOS/onnxruntime.xcframework/ios-arm64_x86_64-simulator"'
  }
end
