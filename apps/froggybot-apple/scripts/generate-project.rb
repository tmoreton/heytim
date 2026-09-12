#!/usr/bin/env ruby
# frozen_string_literal: true

require 'fileutils'
require 'pathname'
require 'xcodeproj'

root = File.expand_path('..', __dir__)
project_path = File.join(root, 'FroggyBotApple.xcodeproj')
FileUtils.rm_rf(project_path)
project = Xcodeproj::Project.new(project_path)
project.root_object.attributes['LastSwiftUpdateCheck'] = '2660'
project.root_object.attributes['LastUpgradeCheck'] = '2660'

app = project.new_target(:application, 'FroggyBotApple', :ios, '17.0')
tests = project.new_target(:unit_test_bundle, 'FroggyBotAppleTests', :ios, '17.0')
ui_tests = project.new_target(:ui_test_bundle, 'FroggyBotAppleUITests', :ios, '17.0')
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
    'PRODUCT_BUNDLE_IDENTIFIER' => 'com.froggybot.app',
    'PRODUCT_NAME' => 'FroggyBot',
    'PRODUCT_MODULE_NAME' => 'FroggyBotApple',
    'ASSETCATALOG_COMPILER_APPICON_NAME' => 'AppIcon',
    'INFOPLIST_FILE' => 'Resources/Info.plist',
    'MARKETING_VERSION' => '1.0.0',
    'CURRENT_PROJECT_VERSION' => '1',
    'CODE_SIGN_ENTITLEMENTS[sdk=iphoneos*]' => release ? 'Resources/FroggyBot-iOS-Release.entitlements' : 'Resources/FroggyBot-iOS.entitlements',
    'CODE_SIGN_ENTITLEMENTS[sdk=iphonesimulator*]' => 'Resources/FroggyBot-iOS.entitlements',
    'CODE_SIGN_ENTITLEMENTS[sdk=macosx*]' => release ? 'Resources/FroggyBot-macOS-Release.entitlements' : 'Resources/FroggyBot-macOS.entitlements',
    'ENABLE_APP_SANDBOX[sdk=macosx*]' => 'YES',
    'ENABLE_HARDENED_RUNTIME[sdk=macosx*]' => 'YES',
    'REGISTER_APP_GROUPS' => 'NO',
  )
end

[[tests, 'com.froggybot.app.tests']].each do |target, identifier|
  target.build_configurations.each do |config|
    config.build_settings.merge!(common)
    config.build_settings.merge!(
      'PRODUCT_BUNDLE_IDENTIFIER' => identifier,
      'GENERATE_INFOPLIST_FILE' => 'YES',
      'TEST_HOST[sdk=iphoneos*]' => '$(BUILT_PRODUCTS_DIR)/FroggyBot.app/FroggyBot',
      'TEST_HOST[sdk=iphonesimulator*]' => '$(BUILT_PRODUCTS_DIR)/FroggyBot.app/FroggyBot',
      'TEST_HOST[sdk=macosx*]' => '$(BUILT_PRODUCTS_DIR)/FroggyBot.app/Contents/MacOS/FroggyBot',
      'BUNDLE_LOADER' => '$(TEST_HOST)',
    )
  end
end
ui_tests.build_configurations.each do |config|
  config.build_settings.merge!(common)
  config.build_settings.merge!(
    'PRODUCT_BUNDLE_IDENTIFIER' => 'com.froggybot.app.uitests',
    'GENERATE_INFOPLIST_FILE' => 'YES',
    'TEST_TARGET_NAME' => 'FroggyBotApple',
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
%w[Resources/Info.plist Resources/FroggyBot-iOS.entitlements Resources/FroggyBot-iOS-Release.entitlements Resources/FroggyBot-macOS.entitlements Resources/FroggyBot-macOS-Release.entitlements].each do |relative|
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
local_package.relative_path = '../../packages/frogbot-transcription'
project.root_object.package_references << local_package
nemotron = project.new(Xcodeproj::Project::Object::XCSwiftPackageProductDependency)
nemotron.package = local_package
nemotron.product_name = 'FroggyBotNemotron'
app.package_product_dependencies << nemotron
build_file = project.new(Xcodeproj::Project::Object::PBXBuildFile)
build_file.product_ref = nemotron
app.frameworks_build_phase.files << build_file

project.save
scheme = Xcodeproj::XCScheme.new
scheme.configure_with_targets(app, tests, launch_target: true)
scheme.add_build_target(ui_tests, false)
scheme.add_test_target(ui_tests)
scheme.save_as(project_path, 'FroggyBotApple', true)
puts project_path
