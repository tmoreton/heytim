import XCTest

@MainActor final class FroggyBotAppleUITests: XCTestCase {
  func testNativeSignInMatchesTheFroggyBotFlow() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing-auth"]
    app.launch()

    XCTAssertTrue(app.staticTexts["FroggyBot"].firstMatch.waitForExistence(timeout: 10))
    XCTAssertTrue(app.staticTexts["Welcome back"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.textFields["Email address"].exists)
    XCTAssertTrue(app.buttons["Continue"].exists)
    XCTAssertTrue(app.descendants(matching: .any)["Need an invite? Request beta access"].exists)
  }

  func testNativeConversationLaunchesAndSendsAMessage() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    // A vertically growing SwiftUI TextField is exposed as a TextField on some
    // iOS releases and as a TextView on others, so match its accessible label.
    let composer = app.descendants(matching: .any)["Message Chief"].firstMatch
    XCTAssertTrue(composer.waitForExistence(timeout: 10))

    app.buttons["FroggyBot"].tap()
    XCTAssertTrue(app.searchFields["Search chats"].waitForExistence(timeout: 5))
    let chief = app.staticTexts["Chief"].firstMatch
    XCTAssertTrue(chief.waitForExistence(timeout: 5))
    chief.tap()
    XCTAssertTrue(composer.waitForExistence(timeout: 5))

    composer.tap()
    composer.typeText("Native smoke test")
    app.buttons["Send message"].tap()
    XCTAssertTrue(
      app.staticTexts["This is the native app’s offline test reply."].waitForExistence(timeout: 5))
  }

  func testAccountSettingsUsesTheFroggyBotLayout() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    app.buttons["FroggyBot"].tap()
    let settings = app.buttons["Open account settings"]
    XCTAssertTrue(settings.waitForExistence(timeout: 10))
    XCTAssertTrue(settings.isHittable)
    settings.tap()

    XCTAssertTrue(app.staticTexts["Settings"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["Memory"].exists)
    XCTAssertTrue(app.staticTexts["Skills & tools"].exists)
    XCTAssertTrue(app.staticTexts["Connections"].exists)
    XCTAssertTrue(app.buttons["Done"].exists)

    let exportMemory = app.buttons["Export Memory"]
    for _ in 0..<4 where !exportMemory.exists { app.swipeUp() }
    XCTAssertTrue(exportMemory.waitForExistence(timeout: 5))

    let aboutValue = app.staticTexts["App, FroggyBot for Apple"]
    for _ in 0..<4 where !aboutValue.exists { app.swipeUp() }
    XCTAssertTrue(aboutValue.waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["Platforms, iPhone + Mac"].exists)
  }
}
