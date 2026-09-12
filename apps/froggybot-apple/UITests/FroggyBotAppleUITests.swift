import XCTest

@MainActor final class FroggyBotAppleUITests: XCTestCase {
  func testNativeConversationLaunchesAndSendsAMessage() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    let chief = app.staticTexts["Chief"].firstMatch
    XCTAssertTrue(chief.waitForExistence(timeout: 10))

    let composer = app.textFields["Message Chief"]
    if !composer.waitForExistence(timeout: 2) { chief.tap() }
    XCTAssertTrue(composer.waitForExistence(timeout: 5))
    composer.tap()
    composer.typeText("Native smoke test")
    app.buttons["Send message"].tap()
    XCTAssertTrue(
      app.staticTexts["This is the native app’s offline test reply."].waitForExistence(timeout: 5))
  }
}
