#!/usr/bin/env ruby
# frozen_string_literal: true

require 'fileutils'
require 'pathname'
require 'xcodeproj'

root = File.expand_path('..', __dir__)
project_path = File.join(root, 'HeyTimApple.xcodeproj')
FileUtils.rm_rf(project_path)
project = Xcodeproj::Project.new(project_path)
project.root_object.attributes['LastSwiftUpdateCheck'] = '2660'
project.root_object.attributes['LastUpgradeCheck'] = '2660'

app = project.new_target(:application, 'HeyTimApple', :ios, '17.0')
app.product_reference.name = 'HeyTim.app'
app.product_reference.path = 'HeyTim.app'
tests = project.new_target(:unit_test_bundle, 'HeyTimAppleTests', :ios, '17.0')
ui_tests = project.new_target(:ui_test_bundle, 'HeyTimAppleUITests', :ios, '17.0')
tests.add_dependency(app)
ui_tests.add_dependency(app)

common = {
  'SDKROOT' => 'auto',
  'SUPPORTED_PLATFORMS' => 'iphoneos iphonesimulator macosx',
  'IPHONEOS_DEPLOYMENT_TARGET' => '17.0',
  'MACOSX_DEPLOYMENT_TARGET' => '14.0',
  'TARGETED_DEVICE_FAMILY' => '1',
  'SWIFT_VERSION' => '6.0',
  'SWIFT_STRICT_CONCURRENCY' => 'complete',
  'CLANG_ENABLE_MODULES' => 'YES',
  'ENABLE_USER_SCRIPT_SANDBOXING' => 'YES',
}

app.build_configurations.each do |config|
  release = config.name == 'Release'
  config.build_settings.merge!(common)
  config.build_settings.merge!(
    'PRODUCT_BUNDLE_IDENTIFIER' => 'ai.heytim.app',
    'PRODUCT_NAME' => 'HeyTim',
    'PRODUCT_MODULE_NAME' => 'HeyTimApple',
    'ASSETCATALOG_COMPILER_APPICON_NAME' => 'AppIcon',
    'INFOPLIST_FILE' => 'Resources/Info.plist',
    'INFOPLIST_FILE[sdk=macosx*]' => 'Resources/Info-macOS.plist',
    'MARKETING_VERSION' => '1.0.1',
    'CURRENT_PROJECT_VERSION' => '202609130148',
    'CODE_SIGN_ENTITLEMENTS[sdk=iphoneos*]' => release ? 'Resources/HeyTim-iOS-Release.entitlements' : 'Resources/HeyTim-iOS.entitlements',
    'CODE_SIGN_ENTITLEMENTS[sdk=iphonesimulator*]' => 'Resources/HeyTim-iOS.entitlements',
    'CODE_SIGN_ENTITLEMENTS[sdk=macosx*]' => release ? 'Resources/HeyTim-macOS-Release.entitlements' : 'Resources/HeyTim-macOS.entitlements',
    'ENABLE_APP_SANDBOX[sdk=macosx*]' => 'NO',
    'ENABLE_HARDENED_RUNTIME[sdk=macosx*]' => 'YES',
    'LD_RUNPATH_SEARCH_PATHS[sdk=macosx*]' => '$(inherited) @executable_path/../Frameworks',
    'HEYTIM_SPARKLE_FEED_URL[sdk=macosx*]' => 'https://github.com/tmoreton/heytim/releases/latest/download/appcast.xml',
    'HEYTIM_SPARKLE_PUBLIC_KEY[sdk=macosx*]' => 'bh9EUBu0gc+V/RonsZAGbcF+/uwvBCP19T3agE7T83A=',
    'ENABLE_USER_SCRIPT_SANDBOXING[sdk=iphoneos*]' => 'NO',
    'ENABLE_USER_SCRIPT_SANDBOXING[sdk=macosx*]' => 'NO',
    'REGISTER_APP_GROUPS' => 'NO',
  )
end

[[tests, 'ai.heytim.app.tests']].each do |target, identifier|
  target.build_configurations.each do |config|
    config.build_settings.merge!(common)
    config.build_settings.merge!(
      'PRODUCT_BUNDLE_IDENTIFIER' => identifier,
      'GENERATE_INFOPLIST_FILE' => 'YES',
      'TEST_HOST[sdk=iphoneos*]' => '$(BUILT_PRODUCTS_DIR)/HeyTim.app/HeyTim',
      'TEST_HOST[sdk=iphonesimulator*]' => '$(BUILT_PRODUCTS_DIR)/HeyTim.app/HeyTim',
      'TEST_HOST[sdk=macosx*]' => '$(BUILT_PRODUCTS_DIR)/HeyTim.app/Contents/MacOS/HeyTim',
      'BUNDLE_LOADER' => '$(TEST_HOST)',
    )
  end
end
ui_tests.build_configurations.each do |config|
  config.build_settings.merge!(common)
  config.build_settings.merge!(
    'PRODUCT_BUNDLE_IDENTIFIER' => 'ai.heytim.app.uitests',
    'GENERATE_INFOPLIST_FILE' => 'YES',
    'TEST_TARGET_NAME' => 'HeyTimApple',
  )
end

source_files = Dir.glob(File.join(root, '{App,Sources}', '**', '*.swift')).sort
source_files.each do |path|
  ref = project.main_group.new_file(Pathname(path).relative_path_from(Pathname(root)).to_s)
  app.source_build_phase.add_file_reference(ref)
end

resource_files = %w[Resources/amplify_outputs.json Resources/PrivacyInfo.xcprivacy Resources/Assets.xcassets]
resource_files.each do |relative|
  ref = project.main_group.new_file(relative)
  app.resources_build_phase.add_file_reference(ref)
end
%w[Resources/Info.plist Resources/Info-macOS.plist Resources/DeveloperIDExportOptions.plist Resources/HeyTim-iOS.entitlements Resources/HeyTim-iOS-Release.entitlements Resources/HeyTim-macOS.entitlements Resources/HeyTim-macOS-Release.entitlements].each do |relative|
  project.main_group.new_file(relative)
end

Dir.glob(File.join(root, 'Tests', '*.swift')).sort.each do |path|
  ref = project.main_group.new_file(Pathname(path).relative_path_from(Pathname(root)).to_s)
  tests.source_build_phase.add_file_reference(ref)
end
Dir.glob(File.join(root, 'UITests', '*.swift')).sort.each do |path|
  ref = project.main_group.new_file(Pathname(path).relative_path_from(Pathname(root)).to_s)
  ui_tests.source_build_phase.add_file_reference(ref)
end

local_package = project.new(Xcodeproj::Project::Object::XCLocalSwiftPackageReference)
local_package.relative_path = '../../packages/heytim-transcription'
project.root_object.package_references << local_package
parakeet = project.new(Xcodeproj::Project::Object::XCSwiftPackageProductDependency)
parakeet.package = local_package
parakeet.product_name = 'HeyTimParakeet'
app.package_product_dependencies << parakeet
build_file = project.new(Xcodeproj::Project::Object::PBXBuildFile)
build_file.product_ref = parakeet
app.frameworks_build_phase.files << build_file

def add_remote_product(project, target, url:, requirement:, product:, platforms: [])
  package = project.new(Xcodeproj::Project::Object::XCRemoteSwiftPackageReference)
  package.repositoryURL = url
  package.requirement = requirement
  project.root_object.package_references << package

  dependency = project.new(Xcodeproj::Project::Object::XCSwiftPackageProductDependency)
  dependency.package = package
  dependency.product_name = product
  target.package_product_dependencies << dependency

  link = project.new(Xcodeproj::Project::Object::PBXBuildFile)
  link.product_ref = dependency
  link.platform_filters = platforms unless platforms.empty?
  target.frameworks_build_phase.files << link
end

add_remote_product(
  project,
  app,
  url: 'https://github.com/sparkle-project/Sparkle.git',
  requirement: { 'kind' => 'exactVersion', 'version' => '2.10.0' },
  product: 'Sparkle',
  platforms: ['macos']
)
add_remote_product(
  project,
  app,
  url: 'https://github.com/FluidInference/FluidUse.git',
  requirement: { 'kind' => 'revision', 'revision' => 'e9e95935075b626a203bb20c0645975be23f15b1' },
  product: 'FluidUse',
  platforms: ['macos']
)

# SwiftPM links these XCFramework slices statically into the app, but Xcode also
# copies framework-shaped wrappers into iOS device and macOS products. They are
# not load dependencies and only add redundant bundles and symbol-upload noise.
strip_static_speech = app.new_shell_script_build_phase(
  'Remove unused static speech framework wrappers'
)
strip_static_speech.shell_script = <<~'SCRIPT'
  # The libraries are already linked into the app binary; remove only copied wrappers.
  case "$PLATFORM_NAME" in
    iphoneos|macosx)
      for framework_name in onnxruntime SherpaOnnxC; do
        framework_path="$TARGET_BUILD_DIR/$FRAMEWORKS_FOLDER_PATH/$framework_name.framework"
        if [ -d "$framework_path" ]; then
          /usr/bin/find "$framework_path" -depth -delete
        fi
      done
      ;;
  esac
SCRIPT
strip_static_speech.always_out_of_date = '1'

# Bundle the pinned Core ML checkpoint with the Mac app. The preparation script
# verifies every asset; the installed app never downloads weights on demand.
bundle_laya = app.new_shell_script_build_phase('Bundle Laya for Mac')
bundle_laya.shell_script = <<~'SCRIPT'
  if [ "$PLATFORM_NAME" = macosx ]; then
    "$SRCROOT/scripts/prepare-laya.sh"
    /usr/bin/ditto "$SRCROOT/Generated/Laya/laya-coreml" \
      "$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/laya-coreml"
  fi
SCRIPT
bundle_laya.always_out_of_date = '1'

project.save
scheme = Xcodeproj::XCScheme.new
scheme.configure_with_targets(app, tests, launch_target: true)
scheme.add_build_target(ui_tests, false)
scheme.add_test_target(ui_tests)
scheme.save_as(project_path, 'HeyTimApple', true)

# Keep Mac unit-test verification isolated from the UI-test target. The Mac
# verification build intentionally disables code signing, and including the UI
# target there causes Xcode to create an unsigned *UITests-Runner.app that
# Gatekeeper repeatedly rejects even though only unit tests were requested.
unit_scheme = Xcodeproj::XCScheme.new
unit_scheme.configure_with_targets(app, tests, launch_target: true)
unit_scheme.save_as(project_path, 'HeyTimAppleUnit', true)

# Keep a focused UI-test scheme so simulator checks do not also assemble the
# large speech-model unit-test bundle. The main scheme remains the complete
# app + unit + UI suite used by CI and release verification.
ui_scheme = Xcodeproj::XCScheme.new
ui_scheme.configure_with_targets(app, ui_tests, launch_target: true)
# Xcode 26 can fail before launching UI tests when this focused scheme forces
# LLDB (DebuggerVersionStore reports that no debugger version is available).
# UI tests do not require an attached debugger in verification or release jobs,
# so use Xcode's standard non-debug launcher for this test-only scheme.
ui_scheme.test_action.xml_element.attributes['selectedDebuggerIdentifier'] = ''
ui_scheme.test_action.xml_element.attributes['selectedLauncherIdentifier'] =
  'Xcode.IDEFoundation.Launcher.PosixSpawn'
ui_scheme.save_as(project_path, 'HeyTimAppleUI', true)
puts project_path
